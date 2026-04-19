import pytest
import importlib

from nova.tools.web_search import web_search


class MockResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class MockAsyncClient:
    last_call = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        MockAsyncClient.last_call = {
            "url": url,
            "headers": headers,
            "json": json,
        }
        return MockResponse(
            'event: message\ndata: {"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"### Weather\\nhttps://example.com\\nSunny"}]}}\n'
        )


@pytest.mark.asyncio
async def test_web_search_uses_mcp_exa_without_bearer_header(monkeypatch):
    web_search_module = importlib.import_module("nova.tools.web_search")

    monkeypatch.setattr(web_search_module.httpx, "AsyncClient", MockAsyncClient)

    result = await web_search("current weather")

    assert result.success is True
    assert "### Weather" in result.content
    assert MockAsyncClient.last_call["url"] == "https://mcp.exa.ai/mcp"
    assert MockAsyncClient.last_call["headers"] == {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    assert MockAsyncClient.last_call["json"] == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "web_search_exa",
            "arguments": {
                "query": "current weather",
                "type": "auto",
                "numResults": 8,
                "livecrawl": "fallback",
            },
        },
    }
