"""The 429 split: a spent quota fails fast, everything else is retried.

429 is "Too Many Requests". The status alone does not say which kind of "too
many" it is, and the body is the only thing that does. Two of the things it can
mean are transient -- a rate limit, which clears on its own, and an endpoint
briefly unable to serve anybody -- and one is not: the account is out of credit,
and no amount of waiting will change that.

The policy reads the body for the *permanent* case and retries otherwise, which
is the standard handling and the safer default here. The two directions of
mistake are not symmetric: retrying a 429 that turns out to be permanent costs
one request, while refusing to retry a rate limit fails a turn that would have
succeeded a second later. So the narrow list is the terminal one.

An earlier version had this backwards -- it retried only a body it could
positively read as "capacity", which failed fast on the ordinary rate limit that
429 exists to report. That also named the endpoint-unavailable case "capacity",
a word the status does not use; 429 has no notion of capacity, only of too many
requests.

The observed failure that started this, from the free OpenCode Zen endpoint:

    HTTP 429 ... {"error":{"type":"server_error","message":"Upstream request
    failed: Endpoint is unavailable."}}
"""

from __future__ import annotations

import pytest

from nova.llm.provider import (
    QUOTA_429_MARKERS,
    RETRY_STATUS_CODES,
    is_terminal_429,
)

# The real body, verbatim, from the endpoint this was built for.
UNAVAILABLE = (
    '{"error":{"type":"server_error","message":"Upstream request failed: '
    'Endpoint is unavailable."}}'
)
QUOTA = '{"error":{"type":"insufficient_quota","message":"You exceeded your current quota"}}'


# ── the shared status contract is unchanged ───────────────────────────


def test_429_is_still_not_a_sharedly_retried_status() -> None:
    """The general retry loop is untouched: 429 is handled by its own branch."""
    assert 429 not in RETRY_STATUS_CODES


def test_the_shared_retry_policy_is_still_single_sourced() -> None:
    from nova.llm.providers import anthropic, openai_chat, openai_responses

    for module in (anthropic, openai_chat, openai_responses):
        assert module.RETRY_STATUS_CODES is RETRY_STATUS_CODES, module.__name__


# ── the classifier: terminal means do not bother retrying ─────────────


@pytest.mark.parametrize(
    "body",
    [
        QUOTA,
        "insufficient_quota",
        "billing hard limit reached",
        "your credit balance is too low",
        "you exceeded your current quota",
        # The real body, verbatim, from OpenCode Zen's free tier.
        '{"type":"error","error":{"type":"FreeUsageLimitError","message":'
        '"Free usage limit reached. Free models work in OpenCode '
        '(https://opencode.ai); subscribe to OpenCode Go to keep going: '
        'https://opencode.ai/go"}}',
    ],
)
def test_a_quota_body_is_terminal(body: str) -> None:
    """The one case worth refusing to wait out."""
    assert is_terminal_429(429, body) is True, body


@pytest.mark.parametrize(
    "body",
    [
        UNAVAILABLE,
        "overloaded",
        "capacity reached",
        "temporarily unavailable",
        # The ordinary meaning of the status, and the case the previous policy
        # got wrong by failing fast on it.
        "too many requests",
        "rate limit exceeded",
        "Rate limit reached for gpt-4o in organization org-xxx",
        # A per-minute budget clears on its own; only a spent one is terminal.
        "usage limit per minute exceeded",
        # A body nobody has seen before is retried rather than refused: the cost
        # of being wrong is one request, and the cost of the other direction is
        # a dead turn.
        "",
        "not json at all",
        "{}",
        '{"error":{"message":"something nobody has seen before"}}',
    ],
)
def test_everything_else_is_retryable(body: str) -> None:
    assert is_terminal_429(429, body) is False, body


def test_quota_wins_when_both_signals_are_present() -> None:
    """A body naming both is treated as terminal.

    The direction that costs one prompt rather than burning an allowance the
    user may not have.
    """
    body = "endpoint unavailable; quota exceeded"

    assert is_terminal_429(429, body) is True


def test_a_non_429_is_never_terminal() -> None:
    """The status gate comes first, so this says nothing about a 503, which the
    general loop already handles on its own terms."""
    assert is_terminal_429(503, "endpoint is unavailable") is False
    assert is_terminal_429(200, QUOTA) is False


def test_the_quota_markers_stay_narrow() -> None:
    """Every marker here turns a retryable 429 into a dead turn, so the list is
    a liability as much as a guard and should not grow without a body that
    needs it."""
    assert len(QUOTA_429_MARKERS) <= 8, sorted(QUOTA_429_MARKERS)
