"""Retry policy is shared: 429 must fail fast, never retry.

Quota/throttle feedback is not a transient fault; retrying it only burns
quota faster.
"""

from nova.llm.provider import RETRY_STATUS_CODES
from nova.llm.providers import anthropic, openai_chat, openai_responses


def test_429_not_retried():
    assert 429 not in RETRY_STATUS_CODES


def test_retry_policy_is_single_sourced():
    for module in (anthropic, openai_chat, openai_responses):
        assert module.RETRY_STATUS_CODES is RETRY_STATUS_CODES, module.__name__
