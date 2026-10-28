"""The transcript text stored beside the model-facing message content."""

import json

import pytest

from nova.session.models import decode_display_text, encode_display_text


class TestEncodeDisplayText:
    def test_keeps_a_different_display_text(self):
        data = encode_display_text("look at this", "look at this\nAttached file: `a`")
        assert json.loads(data) == {"display_text": "look at this"}

    def test_skips_when_the_texts_match(self):
        assert encode_display_text("same", "same") is None

    def test_skips_when_no_display_text_is_given(self):
        assert encode_display_text(None, "content") is None

    def test_round_trips_unicode(self):
        data = encode_display_text("看图", "看图\nAttached file: `图.png`")
        assert decode_display_text(data) == "看图"


class TestDecodeDisplayText:
    def test_ignores_a_legacy_content_row(self):
        # Older rows kept the message body itself in `data`.
        assert decode_display_text("plain old content") is None

    def test_ignores_a_json_scalar(self):
        assert decode_display_text('"just a string"') is None

    def test_ignores_a_missing_key(self):
        assert decode_display_text('{"other": 1}') is None

    def test_ignores_none_and_garbage(self):
        assert decode_display_text(None) is None
        assert decode_display_text("{not json") is None


class TestStorage:
    @pytest.mark.asyncio
    async def test_the_display_text_survives_a_round_trip(self):
        from nova.db.in_memory_repository import InMemoryRepository
        from nova.session.models import Session, encode_display_text

        repository = InMemoryRepository()
        await repository.connect()
        await repository.save_session(Session(id="s1"))
        content = "look\nAttached file: `a.ts`"
        await repository.add_message(
            "s1",
            "user",
            content,
            data=encode_display_text("look", content),
        )
        [message] = await repository.get_messages("s1")
        assert message.content == content
        assert decode_display_text(message.data) == "look"
