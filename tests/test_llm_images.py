"""Image reference helpers: data URLs, downscaling, and the request budget."""

from __future__ import annotations

import base64
import io

from PIL import Image

from nova.llm.images import (
    DEFAULT_IMAGE_MIME,
    DOWNSCALE_BYTES,
    DOWNSCALE_MAX_EDGE,
    IMAGE_REMOVED,
    bound_images,
    downscale_image,
    image_data_url,
    image_size_bytes,
    parse_image_ref,
)
from nova.llm.provider import Message


class TestParseImageRef:
    def test_splits_a_data_url(self):
        assert parse_image_ref("data:image/jpeg;base64,QUJD") == (
            "image/jpeg",
            "QUJD",
        )

    def test_tolerates_parameters_after_the_mime(self):
        assert parse_image_ref("data:image/webp;charset=utf-8;base64,QUJD") == (
            "image/webp",
            "QUJD",
        )

    def test_reads_bare_base64_as_png(self):
        assert parse_image_ref("QUJD") == (DEFAULT_IMAGE_MIME, "QUJD")

    def test_missing_mime_falls_back(self):
        mime, payload = parse_image_ref("data:;base64,QUJD")
        assert mime == DEFAULT_IMAGE_MIME
        assert payload == "QUJD"


class TestImageDataUrl:
    def test_round_trips(self):
        assert (
            image_data_url("data:image/gif;base64,R0lG") == "data:image/gif;base64,R0lG"
        )

    def test_wraps_bare_base64(self):
        assert image_data_url("QUJD") == "data:image/png;base64,QUJD"


class TestImageSizeBytes:
    def test_decodes_from_the_base64_length(self):
        # "QUJD" is 4 base64 chars -> 3 bytes ("ABC")
        assert image_size_bytes("data:image/png;base64,QUJD") == 3

    def test_ignores_padding(self):
        assert image_size_bytes("QUI=") == 2

    def test_empty_payload(self):
        assert image_size_bytes("data:image/png;base64,") == 0


def _data_url(image: Image.Image, fmt: str, **kwargs) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/{fmt.lower()};base64,{encoded}"


def _photo(width: int = 3000, height: int = 2000) -> str:
    """A noisy photograph: noise is what makes JPEGs large."""
    noise = Image.effect_noise((width, height), 100).convert("RGB")
    return _data_url(noise, "JPEG", quality=95)


def _ten_byte_image() -> str:
    """A payload whose decoded size is exactly ten bytes."""
    return "data:image/png;base64," + base64.b64encode(b"0123456789").decode()


class TestDownscaleImage:
    def test_a_small_image_is_left_alone(self):
        small = _data_url(Image.new("RGB", (64, 64), "white"), "PNG")
        assert image_size_bytes(small) < DOWNSCALE_BYTES

        assert downscale_image(small) == small

    def test_a_large_photo_is_shrunk_to_the_provider_edge(self):
        original = _photo()
        assert image_size_bytes(original) > DOWNSCALE_BYTES

        smaller = downscale_image(original)

        assert smaller.startswith("data:image/jpeg;base64,")
        assert image_size_bytes(smaller) < image_size_bytes(original) // 4
        payload = base64.b64decode(smaller.partition(",")[2])
        with Image.open(io.BytesIO(payload)) as decoded:
            assert max(decoded.size) <= DOWNSCALE_MAX_EDGE

    def test_transparency_survives_as_png(self):
        noise = Image.effect_noise((2400, 1600), 100)
        alpha = Image.new("L", noise.size, 128)
        original = _data_url(Image.merge("RGBA", (noise, noise, noise, alpha)), "PNG")
        assert image_size_bytes(original) > DOWNSCALE_BYTES

        smaller = downscale_image(original)

        assert smaller.startswith("data:image/png;base64,")
        payload = base64.b64decode(smaller.partition(",")[2])
        with Image.open(io.BytesIO(payload)) as decoded:
            assert decoded.mode == "RGBA"

    def test_an_unreadable_payload_is_returned_unchanged(self):
        junk = base64.b64encode(b"x" * (2 * 1024 * 1024)).decode("ascii")
        ref = "data:image/png;base64," + junk

        assert downscale_image(ref) == ref


class TestBoundImages:
    def test_a_request_under_the_trigger_is_untouched(self):
        messages = [
            Message(role="user", content="a", images=[_ten_byte_image()]),
            Message(role="user", content="b", images=[_ten_byte_image()]),
        ]

        assert bound_images(messages) is messages

    def test_the_oldest_images_are_dropped_first(self):
        messages = [
            Message(role="user", content=f"turn {index}", images=[_ten_byte_image()])
            for index in range(4)
        ]

        bounded = bound_images(messages, trigger=25, target=10)

        assert [message.images is None for message in bounded] == [
            True,
            True,
            False,
            False,
        ]
        assert bounded[0].content == f"turn 0\n\n{IMAGE_REMOVED}"
        assert bounded[1].content == f"turn 1\n\n{IMAGE_REMOVED}"
        assert bounded[2].content == "turn 2"
        assert bounded[3].content == "turn 3"

    def test_a_partly_cut_message_keeps_its_newest_image(self):
        images = [_ten_byte_image() for _ in range(3)]
        messages = [Message(role="user", content="three pictures", images=images)]

        bounded = bound_images(messages, trigger=15, target=5)

        assert bounded[0].images == [images[2]]
        assert bounded[0].content.count(IMAGE_REMOVED) == 1
        # The caller's message is a live object; it must not be rewritten.
        assert messages[0].images == images
        assert messages[0].content == "three pictures"
