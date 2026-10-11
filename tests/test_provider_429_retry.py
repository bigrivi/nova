"""The transport branch: what a capacity 429 does to the POST loop.

The classifier says a body is capacity; this file says what the retry loop then
does, against a fake session that hands back scripted responses. Two properties
carry the weight and each is a way the change could have been wrong in the
dangerous direction:

* The body is read only on the 429 path, and the response handed back on the
  non-retry path still yields it. The caller builds its error message from that
  text, so a consumed body would silently turn "HTTP 429 ... Endpoint is
  unavailable" into "HTTP 429 ... <empty response>" -- the one upstream detail
  the user gets, lost.
* The retry budget is the existing bounded one. A capacity outage is waited
  out for a couple of seconds, not for as long as the upstream keeps saying
  "unavailable"; ``Retry-After`` is honoured but capped.
"""

from __future__ import annotations

import asyncio

import pytest

from nova.llm.http_provider import HttpProvider
from nova.llm.policy import StreamPolicy, TransportPolicy
from nova.llm.provider import MAX_RETRIES

UNAVAILABLE = (
    '{"error":{"type":"server_error","message":"Upstream request failed: '
    'Endpoint is unavailable."}}'
)
QUOTA = '{"error":{"type":"insufficient_quota","message":"You exceeded your quota"}}'


class _Response:
    """One scripted response: a status, a body and headers."""

    def __init__(self, status: int, text: str = "", headers: dict | None = None):
        self.status = status
        self.headers = headers or {}
        self._text = text
        self.released = False

    async def text(self) -> str:
        return self._text

    async def release(self) -> None:
        self.released = True


class _ScriptedSession:
    """Hands back its responses in order, recording how many posts it took."""

    def __init__(self, responses: list[_Response]):
        self._responses = responses
        self.posts = 0

    async def post(self, url, headers=None, json=None, timeout=None):  # type: ignore[no-untyped-def]
        response = self._responses[min(self.posts, len(self._responses) - 1)]
        self.posts += 1
        return response


class _Provider(HttpProvider):
    """Enough of a provider to reach the retry loop."""

    transport_policy = TransportPolicy(
        use_retry=True,
        trust_env=False,
        honor_retry_after=False,
        guard_non_json=True,
        connector_kwargs={},
    )
    stream_policy = StreamPolicy(
        line_limit=None,
        max_content_chars=None,
        max_tool_arg_chars=None,
        swallow_cancel=True,
        cancel_keeps_content=False,
    )
    trace_label = "fake"
    timeout_seconds = 30.0

    def _prepare_request(self, messages, model, stream, tools, session_id, effort):  # type: ignore[no-untyped-def]
        return "https://example.invalid/v1/chat", {}, {}

    def _parse_response(self, data):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _new_parser(self, model):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def count_tokens(self, text, model=None):  # type: ignore[no-untyped-def]
        return 0


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record sleeps instead of taking them."""
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return waits


async def _post(responses: list[_Response], no_sleep: list[float]) -> _Response:
    provider = _Provider()
    session = _ScriptedSession(responses)
    result = await provider._post_with_retry(session, "https://x", {}, {}, None)
    assert result is not None, "the abort path is not under test here"
    return result  # type: ignore[no-any-return]


# ── capacity retries, quota does not ──────────────────────────────────


@pytest.mark.asyncio
async def test_a_capacity_429_is_retried_until_it_succeeds(no_sleep) -> None:
    response = await _post(
        [
            _Response(429, UNAVAILABLE),
            _Response(429, UNAVAILABLE),
            _Response(200, "{}"),
        ],
        no_sleep,
    )

    assert response.status == 200
    assert len(no_sleep) == 2, f"expected two backoffs, got {no_sleep}"
    assert no_sleep[1] > no_sleep[0], "the backoff doubles"


@pytest.mark.asyncio
async def test_a_capacity_429_gives_up_inside_the_bounded_budget(no_sleep) -> None:
    response = await _post([_Response(429, UNAVAILABLE)] * MAX_RETRIES, no_sleep)

    # The last response is handed back so the caller can build its error from
    # it, and the loop stops at MAX_RETRIES rather than waiting the outage out.
    assert response.status == 429
    assert len(no_sleep) == MAX_RETRIES - 1


@pytest.mark.asyncio
async def test_a_quota_429_is_not_retried(no_sleep) -> None:
    response = await _post([_Response(429, QUOTA)], no_sleep)

    assert response.status == 429
    assert no_sleep == [], "a quota refusal must not cost a second request"


@pytest.mark.asyncio
async def test_an_unrecognised_429_is_not_retried(no_sleep) -> None:
    response = await _post([_Response(429, '{"error":"nobody knows"}')], no_sleep)

    assert response.status == 429
    assert no_sleep == []


# ── the body survives, and the wait is capped ─────────────────────────


@pytest.mark.asyncio
async def test_the_body_is_still_readable_when_the_429_is_returned(no_sleep) -> None:
    """The caller's ``await resp.text()`` must still see the upstream detail.

    aiohttp caches what ``text()`` returns, which is what makes it safe for the
    retry branch to read it at all; this pins the contract the caller relies
    on, because a consumed body would degrade the only error text the user sees
    into "<empty response>".
    """
    response = await _post([_Response(429, QUOTA)], no_sleep)

    assert await response.text() == QUOTA


@pytest.mark.asyncio
async def test_retry_after_is_honoured_on_the_capacity_path(no_sleep) -> None:
    await _post(
        [_Response(429, UNAVAILABLE, {"Retry-After": "7"}), _Response(200, "{}")],
        no_sleep,
    )

    assert no_sleep == [7.0]


@pytest.mark.asyncio
async def test_an_absurd_retry_after_is_capped(no_sleep) -> None:
    await _post(
        [_Response(429, UNAVAILABLE, {"Retry-After": "9999"}), _Response(200, "{}")],
        no_sleep,
    )

    from nova.llm.provider import CAPACITY_429_MAX_WAIT

    assert no_sleep == [CAPACITY_429_MAX_WAIT]


@pytest.mark.asyncio
async def test_a_nonsense_retry_after_falls_back_to_the_backoff(no_sleep) -> None:
    await _post(
        [_Response(429, UNAVAILABLE, {"Retry-After": "soon"}), _Response(200, "{}")],
        no_sleep,
    )

    assert no_sleep == [1.0], "the base delay, since the header is unusable"


# ── the per-provider switch ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_provider_can_decline_the_capacity_retry(no_sleep) -> None:
    class _NoRetry(_Provider):
        transport_policy = TransportPolicy(
            use_retry=True,
            trust_env=False,
            honor_retry_after=False,
            guard_non_json=True,
            retry_capacity_429=False,
            connector_kwargs={},
        )

    provider = _NoRetry()
    session = _ScriptedSession([_Response(429, UNAVAILABLE)])
    response = await provider._post_with_retry(session, "https://x", {}, {}, None)

    assert response is not None and response.status == 429
    assert session.posts == 1
    assert no_sleep == []


@pytest.mark.asyncio
async def test_a_provider_without_retry_never_reaches_the_branch(no_sleep) -> None:
    class _SinglePost(_Provider):
        transport_policy = TransportPolicy(
            use_retry=False,
            trust_env=False,
            honor_retry_after=False,
            guard_non_json=True,
            connector_kwargs={},
        )

    provider = _SinglePost()
    session = _ScriptedSession([_Response(429, UNAVAILABLE), _Response(200, "{}")])
    response = await provider._post_with_retry(session, "https://x", {}, {}, None)

    assert response is not None and response.status == 429
    assert session.posts == 1


# ── the 5xx path is untouched ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_503_still_retries_through_the_general_loop(no_sleep) -> None:
    response = await _post(
        [_Response(503, "unavailable"), _Response(200, "{}")], no_sleep
    )

    assert response.status == 200
    assert no_sleep == [1.0]
