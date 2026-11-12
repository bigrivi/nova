"""Image references carried by a user message.

A message stores images as data URLs (``data:image/jpeg;base64,…``) so the media
type survives the session round-trip. Rows written before that change hold bare
base64, which is read as PNG — the only format the old code ever produced.
"""

from __future__ import annotations

import base64
import dataclasses
import io
import logging
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from nova.llm.provider import Message

log = logging.getLogger(__name__)

DEFAULT_IMAGE_MIME = "image/png"

#: Largest single image accepted from a client. Providers cap lower (Anthropic
#: 5 MB, most OpenAI-compatible endpoints 20 MB), so this is the outer bound.
MAX_IMAGE_BYTES = 20 * 1024 * 1024

#: Largest total image payload on one message.
MAX_IMAGES_BYTES = 40 * 1024 * 1024

#: Below this, an image's bytes are left alone: re-encoding a small file buys
#: nothing and costs a decode.
DOWNSCALE_BYTES = 1536 * 1024

#: Longest edge a provider keeps. Anthropic downscales to this itself, so bytes
#: above it never reach the model; sending them only pays for the upload.
DOWNSCALE_MAX_EDGE = 1568

#: JPEG quality for a re-encoded photograph. Visually lossless at this size.
DOWNSCALE_QUALITY = 82

#: Total image bytes one request may carry before the oldest are dropped.
BOUND_TRIGGER_BYTES = 25 * 1024 * 1024

#: What the oldest images are dropped down to once the trigger is crossed.
BOUND_TARGET_BYTES = 15 * 1024 * 1024

#: Model-facing text standing in for an image that was dropped. It says both
#: what happened and what to do instead, because a model that only sees a gap
#: invents the contents.
IMAGE_REMOVED = (
    "[This image was removed to reduce the request size and is no longer visible. "
    "Do not make claims about its contents from memory. If needed, read it again "
    "with a tool or ask the user to attach it again.]"
)


def parse_image_ref(ref: str) -> tuple[str, str]:
    """Split an image reference into media type and base64 payload.

    Args:
        ref: A data URL, or a bare base64 string from an older session row.

    Returns:
        ``(mime, base64)``; bare base64 is reported as ``image/png``.
    """
    if not ref.startswith("data:"):
        return DEFAULT_IMAGE_MIME, ref
    header, _, payload = ref.partition(",")
    mime = header[5:].split(";", 1)[0].strip()
    return (mime or DEFAULT_IMAGE_MIME, payload)


def image_data_url(ref: str) -> str:
    """Normalise *ref* to a ``data:<mime>;base64,`` URL."""
    mime, payload = parse_image_ref(ref)
    return f"data:{mime};base64,{payload}"


def image_size_bytes(ref: str) -> int:
    """Decoded size of *ref* without allocating the bytes.

    Args:
        ref: A data URL or bare base64 string.

    Returns:
        Size in bytes implied by the base64 length (0 for an empty payload).
    """
    _, payload = parse_image_ref(ref)
    stripped = payload.rstrip("=")
    return (len(stripped) * 3) // 4


def downscale_image(ref: str) -> str:
    """Re-encode an oversized image down to what a provider will actually use.

    A photograph straight off a phone is several megabytes, and base64 makes it
    a third bigger again — bytes that ride in every later request of the session
    and sit in the database forever. Every major provider resizes the picture
    before looking at it, so those bytes buy nothing. Shrinking it here costs one
    decode and saves the upload, the storage and the row.

    Anything that cannot be decoded is returned unchanged: an image that defeats
    the optimiser must not take the turn down with it.

    Args:
        ref: A data URL, or bare base64 as tool results carry it.

    Returns:
        A ``data:<mime>;base64,`` URL no larger than :data:`DOWNSCALE_MAX_EDGE`
        on its longest edge, or *ref* itself when it is small or unreadable.
    """
    if image_size_bytes(ref) <= DOWNSCALE_BYTES:
        return ref

    _, payload = parse_image_ref(ref)
    try:
        raw = base64.b64decode(payload)
        with Image.open(io.BytesIO(raw)) as image:
            has_alpha = image.mode in ("RGBA", "LA", "PA") or (
                "transparency" in image.info
            )
            image.thumbnail(
                (DOWNSCALE_MAX_EDGE, DOWNSCALE_MAX_EDGE), Image.Resampling.LANCZOS
            )
            buffer = io.BytesIO()
            if has_alpha:
                image.save(buffer, format="PNG", optimize=True)
                mime = "image/png"
            else:
                image.convert("RGB").save(
                    buffer,
                    format="JPEG",
                    quality=DOWNSCALE_QUALITY,
                    optimize=True,
                )
                mime = "image/jpeg"
    except Exception:
        log.debug("image could not be downscaled; sending it as it arrived")
        return ref

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def bound_images(
    messages: list[Message],
    *,
    trigger: int = BOUND_TRIGGER_BYTES,
    target: int = BOUND_TARGET_BYTES,
) -> list[Message]:
    """Drop the oldest images until one request's image payload fits.

    Images stay in the history and are replayed on every turn, so a long session
    hands the provider every picture it ever saw. The newest ones are the ones
    the conversation is about; the oldest are the cheapest to lose, and the
    placeholder tells the model it can fetch one back with a tool.

    The cut is batched rather than trimmed to exactly *target*: a new image then
    moves it only every ``trigger - target`` bytes, which leaves the replaced
    prefix — and the provider's prompt cache — alone between cuts.

    Args:
        messages: The request's messages, in order.
        trigger: Total image bytes that may be carried before anything is cut.
        target: What the kept payload is cut down to when the trigger is crossed.

    Returns:
        A new list when something was dropped, otherwise *messages* itself. The
        input messages are never mutated.
    """
    sizes = [
        image_size_bytes(ref) for message in messages for ref in (message.images or [])
    ]
    if sum(sizes) <= trigger:
        return messages

    cut = 0
    kept = 0
    for size in sizes:
        kept += size
        if kept <= trigger:
            continue
        while kept > target and cut < len(sizes):
            kept -= sizes[cut]
            cut += 1

    bounded: list[Message] = []
    index = 0
    for message in messages:
        if not message.images:
            bounded.append(message)
            continue
        surviving: list[str] = []
        dropped = False
        for ref in message.images:
            if index < cut:
                dropped = True
            else:
                surviving.append(ref)
            index += 1
        if not dropped:
            bounded.append(message)
            continue
        bounded.append(
            dataclasses.replace(
                message,
                images=surviving or None,
                content=f"{message.content}\n\n{IMAGE_REMOVED}",
            )
        )
    return bounded
