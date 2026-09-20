"""Retry policy is shared: 429 must fail fast, never retry.

Quota/throttle feedback is not a transient fault; retrying it only burns
quota faster.
"""
from nova.llm import anthropic, openai, openai_response
from nova.llm.provider import RETRY_STATUS_CODES


def test_429_not_retried():
    assert 429 not in RETRY_STATUS_CODES


def test_retry_policy_is_single_sourced():
    for module in (anthropic, openai, openai_response):
        assert module.RETRY_STATUS_CODES is RETRY_STATUS_CODES, module.__name__
