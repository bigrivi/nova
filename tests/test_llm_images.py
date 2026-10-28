"""Image reference helpers: data URLs, and the PNG fallback for old rows."""

from nova.llm.images import (
    DEFAULT_IMAGE_MIME,
    image_data_url,
    image_size_bytes,
    parse_image_ref,
)


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
