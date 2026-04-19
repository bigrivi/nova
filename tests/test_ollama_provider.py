import pytest

from nova.llm.ollama import OllamaProvider
from nova.llm.provider import Done


class _FakeAsyncBytesStream:
    def __init__(self, chunks):
        self._iter = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeResponse:
    def __init__(self, chunks=None, status=200, text_body=""):
        self.status = status
        self.content = _FakeAsyncBytesStream(chunks or [])
        self._text_body = text_body

    async def text(self):
        return self._text_body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, response):
        self._response = response

    def post(self, *args, **kwargs):
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_ollama_stream_reports_http_error(monkeypatch):
    provider = OllamaProvider(base_url="http://localhost:11434")

    monkeypatch.setattr(
        "nova.llm.ollama.aiohttp.ClientSession",
        lambda *args, **kwargs: _FakeSession(
            _FakeResponse(status=503, text_body='{"error":"model unavailable"}')
        ),
    )

    events = []
    async for event in provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        model="gemma4:26b",
        tools=[],
    ):
        events.append(event)

    assert len(events) == 1
    assert isinstance(events[0], Done)
    assert events[0].content == (
        'Error: HTTP 503 from http://localhost:11434/api/chat: {"error":"model unavailable"}'
    )
