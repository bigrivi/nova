"""The 429 split: quota fails fast, capacity retries, unknowns fail fast.

The first version of this file said 429 was never retried, on the grounds that
quota feedback is not a transient fault and retrying it only burns quota
faster. That reasoning was right about quota and wrong about the other thing a
429 can mean: an endpoint that is briefly unable to serve anybody.

The observed failure that prompted the split, from the free OpenCode Zen
endpoint:

    HTTP 429 ... {"error":{"type":"server_error","message":"Upstream request
    failed: Endpoint is unavailable."}}

Nothing about that is a quota. Failing fast on it turns a two-second capacity
blip into a dead turn, which is the same failure a 503 is retried for.

So the policy is now narrow and the direction of every mistake is the safe one:
a 429 is retried only when its body can be positively read as capacity. A quota
429, a body that will not parse, and a body with both signals all keep the old
fail-fast, because the unforgiving reading costs one prompt and the forgiving
one burns an allowance the user does not have.
"""

from __future__ import annotations

import pytest

from nova.llm.provider import (
    CAPACITY_429_MARKERS,
    QUOTA_429_MARKERS,
    RETRY_STATUS_CODES,
    is_capacity_429,
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


# ── the classifier ────────────────────────────────────────────────────


@pytest.mark.parametrize("body", [UNAVAILABLE, "overloaded", "capacity reached"])
def test_an_availability_body_is_capacity(body: str) -> None:
    assert is_capacity_429(429, body) is True, body


@pytest.mark.parametrize(
    "body",
    [
        QUOTA,
        "insufficient_quota",
        "billing hard limit reached",
        "your credit balance is too low",
    ],
)
def test_a_quota_body_is_not(body: str) -> None:
    """The case the original policy existed for, and it still fails fast."""
    assert is_capacity_429(429, body) is False, body


@pytest.mark.parametrize(
    "body",
    [
        "",
        "not json at all",
        "{}",
        '{"error":{"message":"something nobody has seen before"}}',
        "too many requests",
        "rate limit exceeded",
    ],
)
def test_an_unrecognised_body_keeps_the_old_behaviour(body: str) -> None:
    """Only a body we can positively read retries.

    A generic throttle is deliberately *not* in the capacity set: per-minute
    rate limiting is the case the fail-fast policy was written for, and
    widening the list would quietly reverse a decision somebody made on
    purpose.
    """
    assert is_capacity_429(429, body) is False, body


def test_quota_wins_when_both_signals_are_present() -> None:
    body = "endpoint unavailable; your quota is exhausted"

    assert is_capacity_429(429, body) is False


def test_a_5xx_is_not_a_429() -> None:
    """The status gate is first: this classifier says nothing about 503s, which
    the general loop already handles."""
    assert is_capacity_429(503, "endpoint is unavailable") is False
    assert is_capacity_429(200, UNAVAILABLE) is False


def test_the_two_marker_sets_do_not_overlap() -> None:
    """An overlap would make the ordering in ``is_capacity_429`` load-bearing
    in a way nothing tests for."""
    assert not (QUOTA_429_MARKERS & CAPACITY_429_MARKERS)
