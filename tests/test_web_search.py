import importlib
import itertools
import json
from types import SimpleNamespace

import httpx
import pytest

from nova.tools.web_search import (
    BACKENDS,
    DEFAULT_LIMIT,
    EXA,
    KEENABLE,
    MAX_LIMIT,
    PARALLEL,
    resolve_limit,
    web_search,
)
from nova.tools.web_search.base import SearchBackendError, extract_mcp_text
from nova.tools.web_search.exa import parse_markdown_hits
from nova.tools.web_search.keenable import DESCRIPTION_LIMIT as KEENABLE_LIMIT
from nova.tools.web_search.parallel import DESCRIPTION_LIMIT as PARALLEL_LIMIT

web_search_module = importlib.import_module("nova.tools.web_search")
transport_module = importlib.import_module("nova.tools.web_search.transport")
# Each backend reads its own credential from its own module's get_settings, so a
# settings stub has to reach every one of them.
_SETTING_READERS = (
    web_search_module,
    importlib.import_module("nova.tools.web_search.exa"),
    importlib.import_module("nova.tools.web_search.parallel"),
    importlib.import_module("nova.tools.web_search.keenable"),
)

#: A page body with a sentinel far past any description budget. Finding the
#: sentinel in a search result means page content leaked into search.
_BODY = ("filler text " * 500) + "PAGE_BODY_SENTINEL"


def _settings(
    provider: str = "auto",
    exa_key: str = "",
    parallel_key: str = "",
    keenable_key: str = "",
):
    return SimpleNamespace(
        web_search=SimpleNamespace(
            provider=provider,
            exa_api_key=exa_key,
            parallel_api_key=parallel_key,
            keenable_api_key=keenable_key,
        )
    )


def _patch_settings(monkeypatch, **settings_kwargs):
    """Point every settings reader at one stub block.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        **settings_kwargs: Overrides for the ``web_search`` settings block.
    """
    stub = lambda: _settings(**settings_kwargs)  # noqa: E731
    for module in _SETTING_READERS:
        monkeypatch.setattr(module, "get_settings", stub)


def _install(monkeypatch, responses, **settings_kwargs):
    """Patch settings and the HTTP client, then return the recording client.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        responses: Response stand-ins or exceptions, replayed per call.
        **settings_kwargs: Overrides for the ``web_search`` settings block.

    Returns:
        An object exposing the recorded ``calls`` and remaining ``responses``.
    """
    recorded = SimpleNamespace(calls=[], responses=list(responses))

    async def post(url, headers=None, json=None):
        recorded.calls.append({"url": url, "headers": headers, "json": json})
        item = recorded.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    class _Client:
        async def __aenter__(self):
            return SimpleNamespace(post=post)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    _patch_settings(monkeypatch, **settings_kwargs)
    monkeypatch.setattr(web_search_module, "_rotation", itertools.count())
    monkeypatch.setattr(
        transport_module.httpx, "AsyncClient", lambda *a, **k: _Client()
    )
    return recorded


def _response(text, status_code=200, headers=None):
    return SimpleNamespace(
        text=text,
        status_code=status_code,
        headers=headers or {},
        json=lambda: json.loads(text),
    )


def _mcp_envelope(text):
    """Wrap a payload in the MCP envelope both MCP backends return."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": text}]},
        }
    )


def _mcp_sse(text):
    """A full MCP response body: the envelope delivered as an SSE stream."""
    return f"event: message\ndata: {_mcp_envelope(text)}\n"


def _exa_sse(text):
    return _mcp_sse(text)


def _exa_block(title, url, highlights):
    """One result in Exa's markdown template."""
    return (
        f"Title: {title}\n"
        f"URL: {url}\n"
        "Published: 2026-08-15T00:00:00.000Z\n"
        "Author: N/A\n"
        f"Highlights:\n{highlights}"
    )


def _exa_payload(count=2):
    blocks = [
        _exa_block(f"Result {i}", f"https://example.com/{i}", f"summary {i} {_BODY}")
        for i in range(1, count + 1)
    ]
    return _exa_sse("\n\n".join(blocks))


def _parallel_inner(hits):
    """Parallel's inner payload: the hits JSON, before the MCP envelope."""
    return json.dumps({"search_id": "s1", "results": hits})


def _parallel_payload(hits):
    """A full Parallel response body: the hits JSON inside an MCP envelope."""
    return _mcp_sse(_parallel_inner(hits))


def _parallel_response(count=1):
    """A Parallel response carrying *count* plain hits."""
    return _parallel_payload([_parallel_hit(i) for i in range(1, count + 1)])


def _keenable_payload(hits):
    return json.dumps({"query": "q", "mode": "pro", "results": hits})


def _parallel_hit(index, description="", excerpts=None):
    return {
        "url": f"https://example.com/{index}",
        "title": f"Result {index}",
        "description": description,
        "publish_date": "2026-01-01",
        "excerpts": excerpts if excerpts is not None else [f"excerpt {index}"],
    }


def _keenable_hit(index, description="", snippet=""):
    return {
        "url": f"https://example.com/{index}",
        "title": f"Result {index}",
        "description": description,
        "snippet": snippet,
        "published_at": "2026-01-01T00:00:00Z",
    }


def _results_of(content):
    """Parse the tool's JSON payload."""
    return json.loads(content)["results"]


# ── the ring ────────────────────────────────────────────────────────────


def test_the_ring_is_registered_and_usable():
    """Every backend in the ring must be constructible and named."""
    assert set(BACKENDS) == {"exa", "parallel", "keenable"}
    for name, backend in BACKENDS.items():
        assert backend.name == name
        assert backend.url.startswith("https://")


def test_rotation_covers_every_backend_without_repeating():
    """A full rotation cycle visits each backend exactly once."""
    web_search_module._rotation = itertools.count()
    first = [b.name for b in web_search_module.rotating_order()]
    second = [b.name for b in web_search_module.rotating_order()]

    assert sorted(first) == sorted(BACKENDS)
    assert first != second


# ── limit clamping ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (5, 5),
        (1, 1),
        (0, 1),
        (-3, 1),
        (999, MAX_LIMIT),
        (MAX_LIMIT, MAX_LIMIT),
        ("x", DEFAULT_LIMIT),
        (None, DEFAULT_LIMIT),
        (3.7, 3),
    ],
)
def test_limit_is_clamped(requested, expected):
    assert resolve_limit(requested) == expected


def test_limit_bounds_are_published_in_the_schema():
    from nova.tools.registry import _tool_metadata

    schema = _tool_metadata["web_search"]["parameters"]["properties"]["limit"]

    assert schema["default"] == DEFAULT_LIMIT
    assert schema["minimum"] == 1
    assert schema["maximum"] == MAX_LIMIT


# ── request shapes ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_keyless_exa_request_shape(monkeypatch):
    client = _install(monkeypatch, [_response(_exa_payload(1))])

    await web_search("nova agent")

    call = client.calls[0]
    assert call["url"] == EXA.url
    assert call["headers"] == {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    arguments = call["json"]["params"]["arguments"]
    assert call["json"]["params"]["name"] == "web_search_exa"
    assert arguments["query"] == "nova agent"
    assert arguments["numResults"] == DEFAULT_LIMIT


@pytest.mark.asyncio
async def test_exa_key_adds_x_api_key_header(monkeypatch):
    client = _install(
        monkeypatch, [_response(_exa_payload(1))], provider="exa", exa_key="exa-secret"
    )

    await web_search("nova agent")

    assert client.calls[0]["headers"]["x-api-key"] == "exa-secret"


@pytest.mark.asyncio
async def test_parallel_request_shape_and_key_bearer(monkeypatch):
    client = _install(
        monkeypatch,
        [_response(_parallel_payload([_parallel_hit(1)]))],
        provider="parallel",
        parallel_key="parallel-secret",
    )

    await web_search("nova agent")

    call = client.calls[0]
    assert call["url"] == PARALLEL.url
    assert call["headers"]["Authorization"] == "Bearer parallel-secret"
    arguments = call["json"]["params"]["arguments"]
    assert arguments["objective"] == "nova agent"
    assert arguments["search_queries"] == ["nova agent"]
    assert isinstance(arguments["session_id"], str)


@pytest.mark.asyncio
async def test_keenable_keyless_request_needs_no_credential(monkeypatch):
    _patch_settings(monkeypatch)
    request = KEENABLE.request("rust tokio", 5)

    assert request.url == "https://api.keenable.ai/v1/search/public"
    assert request.headers["X-Keenable-Title"] == "nova"
    assert "X-API-Key" not in request.headers
    assert request.body == {"query": "rust tokio", "mode": "pro"}
    # No MCP envelope: this backend is plain REST.
    assert "jsonrpc" not in request.body


@pytest.mark.asyncio
async def test_keenable_key_switches_to_the_authenticated_path(monkeypatch):
    _patch_settings(monkeypatch, keenable_key="kn-key")
    request = KEENABLE.request("rust tokio", 5)

    assert request.url == "https://api.keenable.ai/v1/search"
    assert request.headers["X-API-Key"] == "kn-key"


# ── Exa's markdown reverse-parse ────────────────────────────────────────


def test_exa_markdown_is_recovered_into_rows():
    hits = parse_markdown_hits(
        _exa_block(
            "异步编程基础", "https://doc.rust-lang.net.cn/ch17.html", "我们让计算机执行"
        ),
        5,
    )

    assert len(hits) == 1
    assert hits[0].title == "异步编程基础"
    assert hits[0].url == "https://doc.rust-lang.net.cn/ch17.html"
    assert hits[0].description == "我们让计算机执行"
    assert hits[0].published == "2026-08-15"


def test_exa_block_without_a_url_is_dropped_not_fatal():
    text = "\n\n".join(
        [
            _exa_block("Good", "https://example.com/ok", "fine"),
            "Title: No URL here\nPublished: 2026-01-01\nHighlights:\norphan",
            _exa_block("Also good", "https://example.com/ok2", "fine"),
        ]
    )

    hits = parse_markdown_hits(text, 5)

    assert [hit.url for hit in hits] == [
        "https://example.com/ok",
        "https://example.com/ok2",
    ]


def test_exa_markdown_without_highlights_still_yields_a_row():
    text = "Title: Bare\nURL: https://example.com/bare\nPublished: N/A"

    hits = parse_markdown_hits(text, 5)

    assert len(hits) == 1
    assert hits[0].description == ""
    # "N/A" is dropped rather than shown to the model as a date.
    assert hits[0].published == ""


def test_exa_parse_honours_the_limit():
    hits = parse_markdown_hits(
        "\n\n".join(
            _exa_block(f"R{i}", f"https://example.com/{i}", "x") for i in range(1, 6)
        ),
        3,
    )

    assert len(hits) == 3


# ── structured backends ─────────────────────────────────────────────────


def test_parallel_rows_map_fields():
    hits = PARALLEL.rows(
        _parallel_inner([_parallel_hit(1, description="A summary")]), 5
    )

    assert hits[0].title == "Result 1"
    assert hits[0].url == "https://example.com/1"
    assert hits[0].description == "A summary"
    assert hits[0].published == "2026-01-01"


def test_parallel_falls_back_to_excerpts_when_description_is_empty():
    hits = PARALLEL.rows(_parallel_inner([_parallel_hit(1)]), 5)

    assert hits[0].description == "excerpt 1"


def test_parallel_caps_the_description():
    hits = PARALLEL.rows(_parallel_inner([_parallel_hit(1, description="x" * 5000)]), 5)

    assert len(hits[0].description) == PARALLEL_LIMIT


def test_parallel_rejects_non_json_payload():
    with pytest.raises(SearchBackendError, match="not JSON"):
        PARALLEL.rows("<html>nope</html>", 5)


def test_parallel_rejects_payload_without_results():
    with pytest.raises(SearchBackendError, match="no results list"):
        PARALLEL.rows(json.dumps({"search_id": "s"}), 5)


def test_keenable_rows_map_fields():
    hits = KEENABLE.rows_from_payload(
        {"results": [_keenable_hit(1, description="Keen summary")]}, 5
    )

    assert hits[0].title == "Result 1"
    assert hits[0].url == "https://example.com/1"
    assert hits[0].description == "Keen summary"
    assert hits[0].published == "2026-01-01"


def test_keenable_falls_back_to_snippet_when_description_is_empty():
    hits = KEENABLE.rows_from_payload(
        {"results": [_keenable_hit(1, snippet="Snip")]}, 5
    )

    assert hits[0].description == "Snip"


def test_keenable_caps_the_description():
    hits = KEENABLE.rows_from_payload(
        {"results": [_keenable_hit(1, description="x" * 5000)]}, 5
    )

    assert len(hits[0].description) == KEENABLE_LIMIT


def test_keenable_surfaces_a_rejected_request():
    with pytest.raises(SearchBackendError, match="is not supported"):
        KEENABLE.rows_from_payload(
            {"error": "Invalid parameter", "message": "mode is not supported"}, 5
        )


def test_keenable_rejects_payload_without_results():
    with pytest.raises(SearchBackendError, match="no results list"):
        KEENABLE.rows_from_payload({"query": "q"}, 5)


def test_a_hit_without_a_url_is_skipped():
    hits = KEENABLE.rows_from_payload(
        {"results": [{"title": "No URL"}, _keenable_hit(1)]}, 5
    )

    assert [hit.url for hit in hits] == ["https://example.com/1"]


def test_an_untitled_hit_is_labelled():
    hits = KEENABLE.rows_from_payload(
        {"results": [{"url": "https://example.com/x", "title": ""}]}, 5
    )

    assert hits[0].title == "(untitled)"


# ── the payload the model receives ───────────────────────────────────────


@pytest.mark.asyncio
async def test_output_is_ranked_metadata_json(monkeypatch):
    _install(monkeypatch, [_response(_exa_payload(2))], provider="exa")

    result = await web_search("nova agent")

    results = _results_of(result.content)
    assert [row["position"] for row in results] == [1, 2]
    assert set(results[0]) == {"position", "title", "url", "description", "published"}
    assert results[0]["title"] == "Result 1"
    assert results[0]["url"] == "https://example.com/1"


@pytest.mark.asyncio
async def test_position_keys_lead_the_row(monkeypatch):
    """Key order is part of the contract: the leading keys get read first."""
    _install(monkeypatch, [_response(_exa_payload(1))], provider="exa")

    result = await web_search("nova agent")

    body = json.loads(result.content)["results"][0]
    assert list(body)[:2] == ["position", "title"]


@pytest.mark.asyncio
async def test_search_never_returns_page_content(monkeypatch):
    """The whole point of the split: a page costs a fetch, not a search."""
    _install(monkeypatch, [_response(_exa_payload(2))], provider="exa")

    result = await web_search("nova agent")

    assert result.success is True
    assert "PAGE_BODY_SENTINEL" not in result.content
    # The injected body alone is longer than any metadata payload could be.
    assert len(result.content) < len(_BODY)


@pytest.mark.asyncio
async def test_every_backend_returns_metadata_only(monkeypatch):
    _install(
        monkeypatch,
        [
            _response(_exa_payload(1), headers={"x-ratelimit-remaining": "900"}),
            _response(_parallel_payload([_parallel_hit(1, description="x" * 4000)])),
            _response(_keenable_payload([_keenable_hit(1, description="y" * 4000)])),
        ],
    )
    web_search_module._rotation = itertools.count()

    for _ in range(3):
        result = await web_search("nova agent")
        assert result.success is True
        assert "URL:" not in result.content
        assert json.loads(result.content)["results"]


# ── failover and failure reporting ──────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_falls_back_to_the_peer(monkeypatch):
    client = _install(
        monkeypatch,
        [_response("rate limited", status_code=429), _response(_parallel_response(1))],
    )

    result = await web_search("nova agent")

    assert result.success is True
    assert [call["url"] for call in client.calls] == [EXA.url, PARALLEL.url]


@pytest.mark.asyncio
async def test_rate_limit_message_is_distinguishable(monkeypatch):
    _install(monkeypatch, [_response("nope", status_code=429)] * 3)

    result = await web_search("nova agent")

    assert result.success is False
    assert "rate limit" in result.content
    assert "429" in result.content


@pytest.mark.asyncio
async def test_all_backends_failing_names_each_failure(monkeypatch):
    _install(monkeypatch, [_response("boom", status_code=503)] * 3)

    result = await web_search("nova agent")

    assert result.success is False
    assert "exa returned HTTP 503" in result.content
    assert "parallel returned HTTP 503" in result.content
    assert "keenable returned HTTP 503" in result.content


@pytest.mark.asyncio
async def test_transport_error_names_the_exception_type(monkeypatch):
    """httpx transport errors often have an empty str(); the type is reported."""
    _install(monkeypatch, [httpx.ConnectError("")] * 3)

    result = await web_search("nova agent")

    assert result.success is False
    assert "ConnectError" in result.content


@pytest.mark.asyncio
async def test_timeout_is_reported_as_a_timeout(monkeypatch):
    _install(monkeypatch, [httpx.ReadTimeout("slow")] * 3)

    result = await web_search("nova agent")

    assert result.success is False
    assert "timed out" in result.content


@pytest.mark.asyncio
async def test_empty_match_still_succeeds_and_tells_the_model_what_to_do(monkeypatch):
    """An empty match is not an error, and the peer backend still gets a turn."""
    client = _install(
        monkeypatch,
        [
            _response(_exa_sse("   ")),
            _response(_parallel_payload([])),
            _response(_keenable_payload([])),
        ],
    )

    result = await web_search("nothing at all")

    assert result.success is True
    assert "No search results found" in result.content
    assert "different query" in result.content
    assert [call["url"] for call in client.calls] == [
        EXA.url,
        PARALLEL.url,
        KEENABLE.url,
    ]


@pytest.mark.asyncio
async def test_a_real_failure_beats_an_empty_match(monkeypatch):
    _install(
        monkeypatch,
        [
            _response(_exa_sse("   ")),
            _response("boom", status_code=500),
            _response("boom", status_code=500),
        ],
    )

    result = await web_search("nothing at all")

    assert result.success is False
    assert "parallel returned HTTP 500" in result.content


@pytest.mark.asyncio
async def test_zero_limit_is_clamped_not_treated_as_default(monkeypatch):
    client = _install(monkeypatch, [_response(_exa_payload(3))], provider="exa")

    await web_search("nova agent", limit=0)

    assert client.calls[0]["json"]["params"]["arguments"]["numResults"] == 1


# ── usage accounting ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_search_records_usage(monkeypatch):
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        web_search_module,
        "record_usage",
        lambda backend, outcome, remaining=None: recorded.append((backend, outcome)),
    )
    _install(monkeypatch, [_response(_exa_payload(1))], provider="exa")

    await web_search("nova agent")

    assert recorded == [("exa", "ok")]


@pytest.mark.asyncio
async def test_rate_limit_is_recorded_under_its_own_kind(monkeypatch):
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        web_search_module,
        "record_usage",
        lambda backend, outcome, remaining=None: recorded.append((backend, outcome)),
    )
    _install(
        monkeypatch,
        [_response("nope", status_code=429), _response(_parallel_response(1))],
    )

    await web_search("nova agent")

    assert recorded == [("exa", "rate_limited"), ("parallel", "ok")]


@pytest.mark.asyncio
async def test_empty_match_is_recorded_separately_from_failure(monkeypatch):
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        web_search_module,
        "record_usage",
        lambda backend, outcome, remaining=None: recorded.append((backend, outcome)),
    )
    _install(
        monkeypatch,
        [
            _response(_exa_sse("   ")),
            _response(_parallel_payload([])),
            _response(_keenable_payload([])),
        ],
    )

    await web_search("nothing")

    assert recorded == [("exa", "empty"), ("parallel", "empty"), ("keenable", "empty")]


@pytest.mark.asyncio
async def test_reported_quota_reaches_the_usage_record(monkeypatch):
    recorded: list[tuple[str, str, int | None]] = []
    monkeypatch.setattr(
        web_search_module,
        "record_usage",
        lambda backend, outcome, remaining=None: recorded.append(
            (backend, outcome, remaining)
        ),
    )
    _install(
        monkeypatch,
        [_response(_exa_payload(1), headers={"x-ratelimit-remaining": "912"})],
        provider="exa",
    )

    await web_search("nova agent")

    assert recorded == [("exa", "ok", 912)]


# ── payload extraction ──────────────────────────────────────────────────


def test_extract_mcp_text_handles_both_framings():
    body = {
        "jsonrpc": "2.0",
        "result": {"content": [{"type": "text", "text": "hello"}]},
    }

    assert extract_mcp_text(json.dumps(body)) == "hello"
    assert extract_mcp_text(f"event: message\ndata: {json.dumps(body)}\n") == "hello"
    assert extract_mcp_text("not json at all") == ""
    assert extract_mcp_text("") == ""


def test_extract_mcp_text_ignores_malformed_documents():
    assert extract_mcp_text('data: {"result": "not an object"}') == ""
    assert extract_mcp_text('data: {"result": {"content": []}}') == ""
    assert extract_mcp_text('data: {"error": {"message": "boom"}}') == ""


def test_quota_remaining_is_read_from_the_response_header():
    response = SimpleNamespace(
        text="", status_code=200, headers={"x-ratelimit-remaining": "925"}
    )

    assert transport_module.quota_remaining(response) == 925


def test_quota_remaining_is_absent_when_not_reported():
    response = SimpleNamespace(text="", status_code=200, headers={})

    assert transport_module.quota_remaining(response) is None


def test_quota_remaining_ignores_an_unparsable_header():
    response = SimpleNamespace(
        text="", status_code=200, headers={"x-ratelimit-remaining": "many"}
    )

    assert transport_module.quota_remaining(response) is None


def test_backend_errors_carry_a_machine_readable_kind():
    assert SearchBackendError("x", "rate_limited").kind == "rate_limited"
