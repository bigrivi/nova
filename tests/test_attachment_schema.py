"""Attachment validation: empty or oversized image payloads are refused."""

import pytest
from pydantic import ValidationError

from nova.llm.images import MAX_IMAGE_BYTES
from nova.server.schemas import AttachmentData


def attachment(image: object) -> dict:
    return {
        "id": "a1",
        "type": "image",
        "name": "shot.png",
        "content": [{"type": "image", "image": image}],
    }


def test_accepts_a_normal_image():
    model = AttachmentData(**attachment("data:image/png;base64,QUJD"))
    assert model.name == "shot.png"


def test_rejects_an_empty_payload():
    with pytest.raises(ValidationError):
        AttachmentData(**attachment(""))


def test_rejects_a_non_string_payload():
    with pytest.raises(ValidationError):
        AttachmentData(**attachment({"image": "QUJD"}))


def test_rejects_an_oversized_payload():
    oversized = "A" * ((MAX_IMAGE_BYTES // 3) * 4 + 8)
    with pytest.raises(ValidationError):
        AttachmentData(**attachment(oversized))


def test_documents_are_not_size_checked():
    model = AttachmentData(
        **{
            "id": "a2",
            "type": "document",
            "name": "notes.txt",
            "content": [{"type": "text", "text": "x" * 1000}],
        }
    )
    assert model.type == "document"
