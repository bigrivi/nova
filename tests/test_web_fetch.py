import importlib
from typing import ClassVar

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
    calls: ClassVar[list] = []

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
            '<html><body><h1>Title</h1><p>Hello <a href="https://example.com">world</a></p></body></html>',
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
    assert MockAsyncClient.calls[1]["headers"]["User-Agent"] == "nova"


# ── the character budget ────────────────────────────────────────────────


def _plain_client(body: str, content_type: str = "text/markdown"):
    """A client returning one fixed body, with no Cloudflare detour."""

    class Response:
        status_code = 200
        content = body.encode("utf-8")

        def __init__(self):
            self.headers = {"content-type": content_type}
            self._text = body

        @property
        def text(self) -> str:
            return self._text

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            return Response()

    return Client


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (15000, 15000),
        (1, 2000),
        (0, 2000),
        (-10, 2000),
        (10_000_000, 500_000),
        ("nope", 15000),
        (None, 15000),
    ],
)
def test_char_limit_is_clamped(requested, expected):
    module = importlib.import_module("nova.tools.web_fetch")

    assert module._clamp_char_limit(requested) == expected


@pytest.mark.asyncio
async def test_a_page_within_budget_is_returned_whole(monkeypatch, tmp_path):
    module = importlib.import_module("nova.tools.web_fetch")
    body = "x" * 5000
    monkeypatch.setattr(module.httpx, "AsyncClient", _plain_client(body))

    result = await module.web_fetch("https://example.com")

    assert result.success is True
    assert result.content == body
    assert "omitted" not in result.content


@pytest.mark.asyncio
async def test_an_oversized_page_is_trimmed_head_and_tail(monkeypatch, tmp_path):
    module = importlib.import_module("nova.tools.web_fetch")
    body = "".join(f"{i:07d}" for i in range(8000))  # 56,000 chars
    monkeypatch.setattr(module.httpx, "AsyncClient", _plain_client(body))
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-fetch-budget"))
    module.get_settings.cache_clear()

    result = await module.web_fetch("https://example.com", char_limit=2000)

    assert result.success is True
    # Head and tail survive; the middle does not.
    assert body[:100] in result.content
    assert body[-100:] in result.content
    assert body[1000:2000] not in result.content
    assert "omitted" in result.content
    # The notice names the path the model can read the rest from.
    assert "read tool" in result.content


@pytest.mark.asyncio
async def test_the_full_page_is_written_where_the_notice_points(monkeypatch, tmp_path):
    module = importlib.import_module("nova.tools.web_fetch")
    body = "".join(f"{i:07d}" for i in range(8000))
    monkeypatch.setattr(module.httpx, "AsyncClient", _plain_client(body))
    home = tmp_path / "nova-fetch-offload"
    monkeypatch.setenv("NOVA_HOME", str(home))
    module.get_settings.cache_clear()

    result = await module.web_fetch("https://example.com/page", char_limit=2000)

    stored = home / module.CACHE_DIRNAME
    written = list(stored.glob("*.md"))
    assert len(written) == 1
    assert written[0].read_text(encoding="utf-8") == body
    assert str(written[0]) in result.content


@pytest.mark.asyncio
async def test_the_stored_copy_itself_is_bounded(monkeypatch, tmp_path):
    module = importlib.import_module("nova.tools.web_fetch")
    body = "y" * (module.MAX_STORED_CHARS + 5000)
    monkeypatch.setattr(module.httpx, "AsyncClient", _plain_client(body))
    home = tmp_path / "nova-fetch-capped"
    monkeypatch.setenv("NOVA_HOME", str(home))
    module.get_settings.cache_clear()

    await module.web_fetch("https://example.com/big", char_limit=2000)

    written = next((home / module.CACHE_DIRNAME).glob("*.md"))
    stored = written.read_text(encoding="utf-8")
    assert len(stored) < len(body)
    assert "stored copy truncated" in stored


@pytest.mark.asyncio
async def test_a_failed_offload_still_returns_the_trimmed_text(monkeypatch, tmp_path):
    """An unwritable cache must not lose the page the model asked for."""
    module = importlib.import_module("nova.tools.web_fetch")
    body = "".join(f"{i:07d}" for i in range(8000))
    monkeypatch.setattr(module.httpx, "AsyncClient", _plain_client(body))
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-fetch-unwritable"))
    module.get_settings.cache_clear()

    # A full disk or a read-only cache, which is how this actually fails.
    monkeypatch.setattr(
        module.Path,
        "write_text",
        lambda *a, **k: (_ for _ in ()).throw(OSError("No space left on device")),
    )

    result = await module.web_fetch("https://example.com", char_limit=2000)

    assert result.success is True
    assert "omitted" in result.content
    assert body[:100] in result.content


@pytest.mark.asyncio
async def test_char_limit_is_exposed_in_the_schema():
    from nova.tools.registry import _tool_metadata

    schema = _tool_metadata["web_fetch"]["parameters"]["properties"]["char_limit"]

    assert schema["minimum"] == 2000
    assert schema["maximum"] == 500_000


def test_the_description_points_at_web_fetch():
    """The model must be told the split exists; Nova relies on it."""
    from nova.tools.registry import _tool_metadata

    assert "web_search" in _tool_metadata["web_fetch"]["description"]
