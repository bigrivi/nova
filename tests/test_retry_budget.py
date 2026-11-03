"""Retry budget decisions, without HTTP, asyncio or a provider."""

from __future__ import annotations

import pytest

from nova.llm.policy import RetryBudget

STATUSES = frozenset({500, 502, 503, 504, 529})


def _budget(**overrides) -> RetryBudget:
    values = {
        "use_retry": True,
        "retry_429": True,
        "honor_retry_after": False,
        "statuses": STATUSES,
        "max_retries": 3,
        "retry_429_attempts": 3,
        "base_delay": 1.0,
        "rate_total_budget": 90.0,
    }
    values.update(overrides)
    return RetryBudget(**values)


def test_connection_failures_spend_the_general_budget_with_backoff():
    budget = _budget()

    first = budget.connection_failure()
    second = budget.connection_failure()

    assert (first.attempt, first.total, first.wait_seconds) == (1, 3, 1.0)
    assert (second.attempt, second.total, second.wait_seconds) == (2, 3, 2.0)
    assert budget.connection_failure() is None


def test_retry_after_overrides_backoff_only_when_honoured():
    honoured = _budget(honor_retry_after=True)
    ignored = _budget(honor_retry_after=False)

    with_header = honoured.response_failure(503, retry_after=7.0, terminal_429=False)
    without_policy = ignored.response_failure(503, retry_after=7.0, terminal_429=False)

    assert with_header.wait_seconds == 7.0
    assert without_policy.wait_seconds == 1.0


def test_a_429_has_its_own_budget_and_schedule():
    budget = _budget()

    first = budget.response_failure(429, retry_after=None, terminal_429=False)
    second = budget.response_failure(429, retry_after=5.0, terminal_429=False)

    assert (first.attempt, first.total, first.wait_seconds) == (1, 3, 1.0)
    assert (second.attempt, second.total, second.wait_seconds) == (2, 3, 5.0)
    assert budget.response_failure(429, retry_after=None, terminal_429=False) is None


def test_a_terminal_429_is_handed_straight_back():
    budget = _budget()

    assert budget.response_failure(429, retry_after=1.0, terminal_429=True) is None
    # The refusal did not spend the budget, so a later rate limit can still use it.
    assert (
        budget.response_failure(429, retry_after=None, terminal_429=False) is not None
    )


def test_the_rate_budget_stops_before_the_wall_clock_ceiling():
    budget = _budget(rate_total_budget=3.0)

    assert budget.response_failure(429, retry_after=2.0, terminal_429=False) is not None
    assert budget.response_failure(429, retry_after=2.0, terminal_429=False) is None


def test_retry_429_disabled_leaves_429_to_the_caller():
    budget = _budget(retry_429=False)

    assert budget.response_failure(429, retry_after=1.0, terminal_429=False) is None


def test_no_retry_means_one_attempt_and_no_decisions():
    budget = _budget(use_retry=False)

    assert budget.total_attempts == 1
    assert budget.connection_failure() is None
    assert budget.response_failure(503, retry_after=None, terminal_429=False) is None


def test_the_two_budgets_do_not_consume_each_other():
    budget = _budget(max_retries=2, retry_429_attempts=4)

    assert budget.connection_failure() is not None
    assert budget.connection_failure() is None

    # A 5xx exhaustion must not have spent the 429 allowance.
    assert (
        budget.response_failure(429, retry_after=None, terminal_429=False) is not None
    )


@pytest.mark.parametrize("status", [500, 502, 503, 504, 529])
def test_every_retryable_status_uses_the_general_budget(status: int):
    budget = _budget()

    assert (
        budget.response_failure(status, retry_after=None, terminal_429=False)
        is not None
    )
