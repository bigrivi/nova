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
* The retry budget is bounded, but a capacity 429 gets a *different* bound from
  the general one. It is an endpoint that will come back rather than a request
  that could not be served, so it is worth more attempts than a 5xx -- sharing
  the general three-attempt budget meant giving up after three seconds, which is
  shorter than the outage such a body describes. It is still bounded: the waits
  have a total ceiling and ``Retry-After`` is capped, so an outage never parks the
  turn indefinitely.
"""

from __future__ import annotations

import asyncio
from datetime import UTC

import aiohttp
import pytest
from multidict import CIMultiDict

from nova.llm.http_provider import HttpProvider
from nova.llm.policy import StreamPolicy, TransportPolicy
from nova.llm.provider import (
    MAX_RETRIES,
    RETRY_429_MAX_ATTEMPTS,
    RETRY_429_TOTAL_BUDGET,
    RetryNotice,
)

UNAVAILABLE = (
    '{"error":{"type":"server_error","message":"Upstream request failed: '
    'Endpoint is unavailable."}}'
)
QUOTA = '{"error":{"type":"insufficient_quota","message":"You exceeded your quota"}}'


class _Response:
    """One scripted response: a status, a body and headers."""

    def __init__(self, status: int, text: str = "", headers: dict | None = None):
        self.status = status
        # CIMultiDict, like aiohttp's real response. The header lookup in
        # ``_retry_after_seconds`` is case-insensitive because the real one is,
        # and a plain dict here would let a regression in that go unnoticed --
        # ``{"Retry-After": "7"}.get("retry-after")`` is None, which is exactly
        # the bug the single lookup replaced.
        self.headers = CIMultiDict(headers or {})
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


async def _drive(provider: HttpProvider, session: _ScriptedSession):  # type: ignore[no-untyped-def]
    """Run the retry generator, keeping the response and what it announced.

    ``_post_with_retry`` is a generator so a retry can be reported before it is
    waited out; the last non-notice item is the response.
    """
    response = None
    notices: list[RetryNotice] = []
    async for item in provider._post_with_retry(session, "https://x", {}, {}, None):
        if isinstance(item, RetryNotice):
            notices.append(item)
        else:
            response = item
    return response, notices


async def _post(responses: list[_Response], no_sleep: list[float]) -> _Response:
    """Drive the generator to its final item, discarding the notices."""
    response, _ = await _drive(_Provider(), _ScriptedSession(responses))
    assert response is not None, "the abort path is not under test here"
    return response  # type: ignore[no-any-return]


async def _post_and_notices(
    responses: list[_Response], no_sleep: list[float]
) -> tuple[_Response, list[RetryNotice]]:
    response, notices = await _drive(_Provider(), _ScriptedSession(responses))
    assert response is not None, "the abort path is not under test here"
    return response, notices  # type: ignore[return-value]


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
    response = await _post(
        [_Response(429, UNAVAILABLE)] * RETRY_429_MAX_ATTEMPTS, no_sleep
    )

    # The last response is handed back so the caller can build its error from
    # it, and the loop stops at its own budget rather than waiting the outage
    # out. Unbounded waiting is not the goal; a budget that outlasts a plausible
    # outage is.
    assert response.status == 429
    assert len(no_sleep) == RETRY_429_MAX_ATTEMPTS - 1
    assert sum(no_sleep) > MAX_RETRIES * 2, (
        "the capacity budget must be materially longer than the general one,"
        " or this is the old three-second window under a new name"
    )


@pytest.mark.asyncio
async def test_a_capacity_429_outlasts_what_a_503_would_get(no_sleep) -> None:
    """The two budgets are separate, and this is the property that matters.

    A persistent outage on each path, and the capacity one is retried more
    times. If raising the capacity budget had widened the general one instead,
    a 503 would wait as long as a 429 and this would show it.
    """
    await _post([_Response(429, UNAVAILABLE)] * 20, no_sleep)
    capacity_waits = len(no_sleep)

    no_sleep.clear()
    await _post([_Response(503, "unavailable")] * 20, no_sleep)

    assert capacity_waits > len(no_sleep), (
        f"capacity got {capacity_waits} retries and 503 got {len(no_sleep)};"
        " they must not share one budget"
    )
    assert len(no_sleep) == MAX_RETRIES - 1, "the general budget is unchanged"


@pytest.mark.asyncio
async def test_a_repeated_long_retry_after_cannot_park_the_turn(no_sleep) -> None:
    """The total ceiling, not the per-wait cap, is what bounds this.

    An endpoint that answers every attempt with ``Retry-After: 60`` would
    otherwise sleep five times for a minute each. The accumulated wait stops at
    ``RETRY_429_TOTAL_BUDGET``, and the response comes back so the caller can
    still read the body.
    """
    long_wait = {"Retry-After": "60"}
    response = await _post([_Response(429, UNAVAILABLE, long_wait)] * 20, no_sleep)

    assert response.status == 429
    assert sum(no_sleep) <= RETRY_429_TOTAL_BUDGET, (
        f"slept {sum(no_sleep)}s, past the {RETRY_429_TOTAL_BUDGET}s ceiling"
    )
    assert await response.text() == UNAVAILABLE, (
        "the ceiling returns the response, so the body must still be readable"
    )


@pytest.mark.asyncio
async def test_a_quota_429_is_not_retried(no_sleep) -> None:
    response = await _post([_Response(429, QUOTA)], no_sleep)

    assert response.status == 429
    assert no_sleep == [], "a quota refusal must not cost a second request"


@pytest.mark.asyncio
async def test_an_unrecognised_429_is_retried(no_sleep) -> None:
    """The default is to retry, which is the standard reading of the status.

    An earlier policy retried only a body it could positively read as an
    endpoint outage, so a 429 that said nothing recognisable failed fast. That
    got the common case backwards: 429 means "too many requests", and a body
    nobody has seen before is far more likely to be a rate limit than a spent
    account.
    """
    response = await _post(
        [_Response(429, '{"error":"nobody knows"}'), _Response(200, "{}")], no_sleep
    )

    assert response.status == 200
    assert len(no_sleep) == 1, "one retry, then it succeeded"


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

    from nova.llm.provider import RETRY_429_MAX_WAIT

    assert no_sleep == [RETRY_429_MAX_WAIT]


@pytest.mark.asyncio
async def test_a_nonsense_retry_after_falls_back_to_the_backoff(no_sleep) -> None:
    await _post(
        [_Response(429, UNAVAILABLE, {"Retry-After": "soon"}), _Response(200, "{}")],
        no_sleep,
    )

    assert no_sleep == [1.0], "the base delay, since the header is unusable"


# ── the per-provider switch ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_provider_can_decline_the_429_retry(no_sleep) -> None:
    class _NoRetry(_Provider):
        transport_policy = TransportPolicy(
            use_retry=True,
            trust_env=False,
            honor_retry_after=False,
            guard_non_json=True,
            retry_429=False,
            connector_kwargs={},
        )

    provider = _NoRetry()
    session = _ScriptedSession([_Response(429, UNAVAILABLE)])
    response = None
    async for item in provider._post_with_retry(session, "https://x", {}, {}, None):
        if not isinstance(item, RetryNotice):
            response = item

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
    response = None
    async for item in provider._post_with_retry(session, "https://x", {}, {}, None):
        if not isinstance(item, RetryNotice):
            response = item

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


# ── the notice: what the client is told, and when ─────────────────────


@pytest.mark.asyncio
async def test_a_retry_is_announced_with_the_upstream_reason(no_sleep) -> None:
    """The reason is the upstream's own words, unwrapped from its JSON envelope.

    The envelope is noise in a one-line notice; the message inside is the part a
    user acts on. "Endpoint is unavailable" is worth waiting out, "you are out of
    credit" is not, and only the upstream knows which it sent.
    """
    _, notices = await _post_and_notices(
        [_Response(429, UNAVAILABLE), _Response(200, "{}")], no_sleep
    )

    assert len(notices) == 1
    assert notices[0].attempt == 1
    assert notices[0].total == RETRY_429_MAX_ATTEMPTS
    assert notices[0].wait_seconds == 1.0
    assert notices[0].reason == "Upstream request failed: Endpoint is unavailable."


@pytest.mark.asyncio
async def test_the_notice_arrives_before_the_wait(monkeypatch) -> None:
    """Ordering is the whole reason this is a generator and not a coroutine.

    A notice emitted after the sleep would describe a wait that has already
    happened, which is the same as not telling the client at all.
    """
    log: list[str] = []

    async def fake_sleep(seconds: float) -> None:
        log.append("sleep")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    provider = _Provider()
    session = _ScriptedSession([_Response(429, UNAVAILABLE), _Response(200, "{}")])
    async for item in provider._post_with_retry(session, "https://x", {}, {}, None):
        log.append("notice" if isinstance(item, RetryNotice) else "response")

    assert log == ["notice", "sleep", "response"], log


@pytest.mark.asyncio
async def test_a_connection_error_is_announced_too(no_sleep) -> None:
    """Every retry is announced, not just the 429 one.

    A client cannot tell a silent wait from a hung request whichever branch
    caused it, so the notice is not specific to the status that happens to be
    most common.
    """

    class _Flaky(_ScriptedSession):
        async def post(self, url, headers=None, json=None, timeout=None):  # type: ignore[no-untyped-def]
            self.posts += 1
            if self.posts == 1:
                raise aiohttp.ClientConnectionError("connection reset by peer")
            return _Response(200, "{}")

    provider = _Provider()
    session = _Flaky([])
    notices: list[RetryNotice] = []
    async for item in provider._post_with_retry(session, "https://x", {}, {}, None):
        if isinstance(item, RetryNotice):
            notices.append(item)

    assert len(notices) == 1
    assert "connection reset by peer" in notices[0].reason


# ── Retry-After in both the forms RFC 7231 allows ─────────────────────


@pytest.mark.asyncio
async def test_retry_after_as_an_http_date_is_honoured(no_sleep) -> None:
    """The second form, which a float() parse silently ignores.

    Shared caches and gateways emit a date rather than a delay, so a client that
    only reads the numeric form honours the header for some servers and not
    others, with no way to tell which.
    """
    from datetime import datetime, timedelta
    from email.utils import format_datetime

    when = datetime.now(UTC) + timedelta(seconds=30)
    await _post(
        [
            _Response(429, UNAVAILABLE, {"Retry-After": format_datetime(when)}),
            _Response(200, "{}"),
        ],
        no_sleep,
    )

    assert len(no_sleep) == 1
    assert 28 <= no_sleep[0] <= 30, no_sleep


@pytest.mark.asyncio
async def test_a_retry_after_in_the_past_waits_nothing(no_sleep) -> None:
    """A date that has already passed means "now", not a negative sleep."""
    from datetime import datetime, timedelta
    from email.utils import format_datetime

    when = datetime.now(UTC) - timedelta(seconds=60)
    await _post(
        [
            _Response(429, UNAVAILABLE, {"Retry-After": format_datetime(when)}),
            _Response(200, "{}"),
        ],
        no_sleep,
    )

    assert no_sleep == [0.0]


@pytest.mark.asyncio
async def test_an_empty_retry_after_falls_back(no_sleep) -> None:
    """Present but blank is not a value; the backoff answers instead."""
    await _post(
        [
            _Response(429, UNAVAILABLE, {"Retry-After": "  "}),
            _Response(200, "{}"),
        ],
        no_sleep,
    )

    assert no_sleep == [1.0]
