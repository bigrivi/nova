import importlib

import pytest

from nova.tools.web_fetch import web_fetch


class MockResponse:
    def __init__(self, text: str, status_code: int = 200, headers=None):
        self._text = text
        self.status_code = status_code
        self.headers = headers or {}
        self.content = text.encode("utf-8")

    @property
    def text(self) -> str:
        return self._text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class MockAsyncClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        MockAsyncClient.calls.append({"url": url, "headers": headers})
        if len(MockAsyncClient.calls) == 1:
            return MockResponse(
                "<html><body>blocked</body></html>",
                status_code=403,
                headers={"cf-mitigated": "challenge", "content-type": "text/html"},
            )
        return MockResponse(
            "<html><body><h1>Title</h1><p>Hello <a href=\"https://example.com\">world</a></p></body></html>",
            headers={"content-type": "text/html", "content-length": "95"},
        )


@pytest.mark.asyncio
async def test_web_fetch_retries_cloudflare_and_extracts_text(monkeypatch):
    web_fetch_module = importlib.import_module("nova.tools.web_fetch")
    MockAsyncClient.calls = []
    monkeypatch.setattr(web_fetch_module.httpx, "AsyncClient", MockAsyncClient)

    result = await web_fetch("https://example.com", format="text")

    assert result.success is True
    assert "Title" in result.content
    assert "Hello world" in result.content
    assert len(MockAsyncClient.calls) == 2
    assert MockAsyncClient.calls[0]["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert MockAsyncClient.calls[1]["headers"]["User-Agent"] == "opencode"
