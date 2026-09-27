from __future__ import annotations

import pytest

from nova.agent.overflow import is_context_overflow


class TestErrorTextPatterns:
    @pytest.mark.parametrize("message", [
        "prompt is too long: 213462 tokens > 200000 maximum",
        "prompt too long",
        '{"error":{"type":"request_too_large","message":"Request exceeds the maximum size"}}',
        "Your input exceeds the context window of this model",
        "Requested token count exceeds the model's maximum context length of 131072 tokens",
        "Input length (265330) exceeds model's maximum context length (262144).",
        ("This model's maximum context length is 128000 tokens. However, your "
         "messages resulted in 130000 tokens. Please reduce the length."),
        '{"error":{"code":"context_length_exceeded","message":"too long"}}',
        "prompt too long; exceeded max context length by 512 tokens",
    ])
    def test_recognised_as_overflow(self, message):
        assert is_context_overflow(message) is True

    @pytest.mark.parametrize("message", [
        "connection reset by peer",
        "rate limit exceeded, slow down",
        "HTTP 500 internal server error",
        "invalid api key",
        "",
    ])
    def test_other_errors_are_not_overflow(self, message):
        assert is_context_overflow(message) is False


class TestNonOverflowVeto:
    """Rate limiting must never be mistaken for an oversized prompt.

    The failure this prevents is specific: compaction runs, the retry is rate
    limited too, and the user sees one request become two failures with
    compaction named as the cause.
    """

    @pytest.mark.parametrize("message", [
        "ThrottlingException: Too many tokens, please wait before trying again.",
        "rate limit exceeded, slow down",
        "429 too many requests",
        "Service unavailable: try again",
    ])
    def test_throttling_is_never_overflow(self, message):
        assert is_context_overflow(message) is False

    @pytest.mark.parametrize("message", [
        "You exceeded your current quota, please check your plan and billing details.",
        "insufficient_quota",
        "Error code: 429 - insufficient_quota: You exceeded your current quota.",
    ])
    def test_quota_and_billing_are_never_overflow(self, message):
        assert is_context_overflow(message) is False

    def test_veto_wins_when_both_tables_would_match(self):
        """Precedence, stated directly.

        Synthetic, because the shipped overflow patterns are narrow enough that
        no real throttling message matches one. It is here so that adding a
        looser pattern later cannot quietly reintroduce the false positive: the
        veto is checked first and returns before the overflow patterns run.
        """
        message = "rate limit: input exceeds the context window"
        assert is_context_overflow(message) is False


class TestSilentOverflow:
    def test_usage_above_the_window_is_overflow(self):
        assert is_context_overflow(
            None, context_window=1000, tokens_input=1200) is True

    def test_cached_tokens_count_against_the_window(self):
        assert is_context_overflow(
            None, context_window=1000, tokens_input=600, cache_read_tokens=500,
        ) is True

    def test_usage_within_the_window_is_fine(self):
        assert is_context_overflow(
            None, context_window=1000, tokens_input=900) is False

    def test_window_is_required(self):
        """Without a window there is nothing to compare against."""
        assert is_context_overflow(None, tokens_input=10_000_000) is False

    def test_an_error_supersedes_the_usage_check(self):
        """A rejected request's usage cannot describe a prompt that fit.

        Without this, a rate-limited call that happened to report a large input
        would be read as "too large" and trigger a compaction.
        """
        assert is_context_overflow(
            "rate limit exceeded",
            context_window=1000,
            tokens_input=9999,
        ) is False
