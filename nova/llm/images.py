"""Image references carried by a user message.

A message stores images as data URLs (``data:image/jpeg;base64,…``) so the media
type survives the session round-trip. Rows written before that change hold bare
base64, which is read as PNG — the only format the old code ever produced.
"""

from __future__ import annotations

DEFAULT_IMAGE_MIME = "image/png"

#: Largest single image accepted from a client. Providers cap lower (Anthropic
#: 5 MB, most OpenAI-compatible endpoints 20 MB), so this is the outer bound.
MAX_IMAGE_BYTES = 20 * 1024 * 1024

#: Largest total image payload on one message.
MAX_IMAGES_BYTES = 40 * 1024 * 1024


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
