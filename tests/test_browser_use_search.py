"""The browser's ``web_search`` action consumes web_search's JSON contract.

It navigates to the first result, so it depends on the search tool returning
``{"results": [{"url": ...}]}``. It was written against that shape before the
tool produced it, and passed keyword arguments the tool never had, so the action
raised on every call. Both halves are pinned here.
"""

import importlib
import json

import pytest

from nova.llm import ToolResult

browser_use_module = importlib.import_module("nova.tools.browser_use")


class _FakePage:
    """Just enough page to observe that the action navigated somewhere."""

    def __init__(self):
        self.visited: list[str] = []
        self.url = "about:blank"

    async def goto(self, url, wait_until=None):
        self.visited.append(url)
        self.url = url


def _install(monkeypatch, search_result):
    """Point the action at a fake browser and a stubbed search tool."""
    page = _FakePage()

    async def fake_browser():
        return page

    async def fake_search(**kwargs):
        fake_search.calls.append(kwargs)
        return search_result

    async def fake_state(include_screenshot=False):
        return {
            "url": page.url,
            "title": "",
            "tabs": 1,
            "scroll_info": {"pixels_above": 0, "pixels_below": 0, "total_height": 0},
            "interactive_elements": "",
            "screenshot": None,
        }

    fake_search.calls = []
    monkeypatch.setattr(browser_use_module, "_ensure_browser", fake_browser)
    monkeypatch.setattr(browser_use_module, "web_search_tool", fake_search)
    # The result summary re-reads the page state after every action. Stubbing
    # it keeps this test about the search contract rather than about rendering.
    monkeypatch.setattr(browser_use_module, "_get_state", fake_state)
    return page, fake_search


@pytest.mark.asyncio
async def test_the_action_navigates_to_the_first_result(monkeypatch):
    payload = json.dumps(
        {
            "results": [
                {
                    "position": 1,
                    "title": "First",
                    "url": "https://example.com/first",
                    "description": "d",
                    "published": "",
                },
                {"position": 2, "title": "Second", "url": "https://example.com/second"},
            ]
        }
    )
    page, _search = _install(monkeypatch, ToolResult(success=True, content=payload))

    result = await browser_use_module.browser_use(action="web_search", query="nova")

    assert result.error is None
    assert page.visited == ["https://example.com/first"]


@pytest.mark.asyncio
async def test_the_action_asks_for_one_result(monkeypatch):
    """Search returns metadata only, so one hit is enough to get a URL."""
    payload = json.dumps({"results": [{"url": "https://example.com/only"}]})
    _page, search = _install(monkeypatch, ToolResult(success=True, content=payload))

    await browser_use_module.browser_use(action="web_search", query="nova")

    assert search.calls == [{"query": "nova", "limit": 1}]


@pytest.mark.asyncio
async def test_a_plain_string_result_is_still_navigable(monkeypatch):
    payload = json.dumps({"results": ["https://example.com/bare"]})
    page, _ = _install(monkeypatch, ToolResult(success=True, content=payload))

    await browser_use_module.browser_use(action="web_search", query="nova")

    assert page.visited == ["https://example.com/bare"]


@pytest.mark.asyncio
async def test_a_failed_search_reports_an_error(monkeypatch):
    page, _ = _install(
        monkeypatch, ToolResult(success=False, content="Search error: exa 429")
    )

    result = await browser_use_module.browser_use(action="web_search", query="nova")

    assert result.error == "Search returned no results"
    assert page.visited == []


@pytest.mark.asyncio
async def test_unparsable_search_output_reports_an_error(monkeypatch):
    page, _ = _install(monkeypatch, ToolResult(success=True, content="not json"))

    result = await browser_use_module.browser_use(action="web_search", query="nova")

    assert "Failed to parse" in (result.error or "")
    assert page.visited == []


@pytest.mark.asyncio
async def test_a_missing_query_is_refused_before_searching(monkeypatch):
    page, search = _install(monkeypatch, ToolResult(success=True, content="{}"))

    result = await browser_use_module.browser_use(action="web_search")

    assert result.error == "Query required for web_search"
    assert search.calls == []
    assert page.visited == []
