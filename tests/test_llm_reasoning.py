"""Tests for reasoning effort: which levels a model offers and how it is sent.

The rule these tests pin down is that levels come *only* from config.json.
A gateway alias carries no clue about which ladder it serves, and a wrong
guess is a 400 from the provider, so an undeclared model offers no control.
"""

from __future__ import annotations

import pytest

from nova.llm.reasoning import (
    apply_effort,
    fit_effort,
    resolve_effort_levels,
)


class TestResolveEffortLevels:
    """What the operator declared is the whole answer; nothing is inferred."""

    def test_declared_levels_are_returned_in_order(self):
        levels = resolve_effort_levels(
            "gpt-5.5",
            "openai-compatible",
            {"reasoning_effort_levels": ["low", "medium", "high"]},
        )
        assert levels == ["low", "medium", "high"]

    @pytest.mark.parametrize(
        "model",
        [
            # Names the resolver used to pattern-match. Each declares nothing, so
            # each must now offer nothing - the guess is the thing removed.
            "gpt-5.5",
            "gpt-5.1",
            "gpt-5-pro",
            "deepseek-v4",
            "qwen3.7-plus",
            "grok-4",
            "kimi-k2-0905",
        ],
    )
    def test_a_recognisable_name_still_offers_nothing(self, model):
        assert resolve_effort_levels(model, "openai-compatible", {"name": model}) == []

    def test_alias_cannot_be_guessed(self):
        """A gateway alias gives no signal, so only a declaration opens it."""
        assert resolve_effort_levels("mimo-v2.5", "openai-compatible", {}) == []
        assert resolve_effort_levels(
            "mimo-v2.5",
            "openai-compatible",
            {"reasoning_effort_levels": ["low", "high"]},
        ) == ["low", "high"]

    def test_missing_model_config_offers_nothing(self):
        assert resolve_effort_levels("gpt-5.5", "openai-compatible", None) == []

    @pytest.mark.parametrize(
        "provider_type",
        ["anthropic", "ollama", "faker", ""],
    )
    def test_provider_that_cannot_carry_a_level_offers_nothing(self, provider_type):
        """A declaration is ignored rather than sent and rejected.

        Anthropic has thinking budgets, not efforts; ollama and faker have
        neither, so a level on those is a category error, not a preference.
        """
        assert resolve_effort_levels(
            "claude-opus-5",
            provider_type,
            {"reasoning_effort_levels": ["low", "high"]},
        ) == []

    def test_bare_string_is_accepted_as_one_level(self):
        assert resolve_effort_levels(
            "gpt-5-pro", "openai-response", {"reasoning_effort_levels": "high"}
        ) == ["high"]

    def test_blank_and_duplicate_entries_are_dropped(self):
        assert resolve_effort_levels(
            "gpt-5.5",
            "openai-compatible",
            {"reasoning_effort_levels": ["low", "  ", "high", "low", " high "]},
        ) == ["low", "high"]

    @pytest.mark.parametrize("declared", [[], (), None, 42, {"low": 1}])
    def test_a_declaration_of_nothing_means_no_control(self, declared):
        assert resolve_effort_levels(
            "gpt-5.5", "openai-compatible", {"reasoning_effort_levels": declared}
        ) == []


class TestFitEffort:
    """Every value that reaches a model is filtered by what it declared."""

    def test_a_declared_level_survives(self):
        assert fit_effort(["low", "high"], "high") == "high"

    def test_an_undeclared_level_is_dropped(self):
        assert fit_effort(["low", "high"], "xhigh") is None

    def test_no_levels_means_nothing_survives(self):
        assert fit_effort([], "high") is None

    @pytest.mark.parametrize("effort", [None, ""])
    def test_absent_effort_stays_absent(self, effort):
        assert fit_effort(["low", "high"], effort) is None


class TestApplyEffort:
    """Each wire format has its own spelling; the body is the only place that
    knows it, so a caller never builds either shape by hand."""

    def test_chat_completions_takes_a_flat_field(self):
        assert apply_effort({}, "high", "openai-compatible") == {
            "reasoning_effort": "high"
        }

    def test_responses_api_nests_it(self):
        assert apply_effort({}, "high", "openai-response") == {
            "reasoning": {"effort": "high"}
        }

    def test_config_wins_over_the_per_turn_selection(self):
        """A hand-written level in config.json is a deliberate override.

        `setdefault` is what encodes that precedence, and it is why
        `reasoning_effort` stays in the passthrough keys while
        `reasoning_effort_levels` does not.
        """
        body = apply_effort({"reasoning_effort": "medium"}, "high", "openai-compatible")
        assert body["reasoning_effort"] == "medium"

    def test_existing_nested_reasoning_block_is_kept_intact(self):
        body = apply_effort(
            {"reasoning": {"summary": "auto"}}, "high", "openai-response"
        )
        assert body["reasoning"] == {"summary": "auto"}

    @pytest.mark.parametrize("provider_type", ["anthropic", "ollama", "faker"])
    def test_providers_without_the_concept_are_left_alone(self, provider_type):
        body = {"model": "claude-opus-5"}
        assert apply_effort(body, "high", provider_type) == body

    def test_no_effort_leaves_the_body_untouched(self):
        body = {"model": "gpt-5.5"}
        assert apply_effort(body, None, "openai-compatible") is body


class TestRequestBody:
    """The level has to survive the trip into the actual HTTP payload."""

    @staticmethod
    def _session(monkeypatch):
        from tests.test_openai_provider import _FakeResponse, _install_fake

        return _install_fake(monkeypatch, _FakeResponse(json_data={}))

    @pytest.mark.asyncio
    async def test_selected_level_reaches_the_payload(self, monkeypatch):
        from nova.llm.openai import OpenAIProvider

        session = self._session(monkeypatch)
        provider = OpenAIProvider(api_key="k")
        await provider.chat(
            [{"role": "user", "content": "hi"}],
            model="gpt-5.5",
            reasoning_effort="xhigh",
        )
        assert session.calls[0]["json"]["reasoning_effort"] == "xhigh"

    @pytest.mark.asyncio
    async def test_config_level_outranks_the_selection(self, monkeypatch):
        from nova.llm.openai import OpenAIProvider

        session = self._session(monkeypatch)
        provider = OpenAIProvider(
            api_key="k", request_options={"reasoning_effort": "medium"}
        )
        await provider.chat(
            [{"role": "user", "content": "hi"}],
            model="gpt-5.5",
            reasoning_effort="xhigh",
        )
        assert session.calls[0]["json"]["reasoning_effort"] == "medium"

    @pytest.mark.asyncio
    async def test_no_selection_sends_no_field(self, monkeypatch):
        from nova.llm.openai import OpenAIProvider

        session = self._session(monkeypatch)
        provider = OpenAIProvider(api_key="k")
        await provider.chat([{"role": "user", "content": "hi"}], model="gpt-5.5")
        assert "reasoning_effort" not in session.calls[0]["json"]

    def test_the_level_list_never_leaks_into_the_payload(self, tmp_path):
        """It describes the UI, not the request, so settings must not forward it.

        `reasoning_effort_levels` is in the internal-keys set while
        `reasoning_effort` deliberately is not - one is metadata, the other is
        a request field, and only the latter is meant to reach the provider.
        """
        import json

        from nova.settings import Settings

        home = tmp_path / ".nova"
        home.mkdir()
        (home / "config.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "gw": {
                            "type": "openai-compatible",
                            "name": "gw",
                            "options": {"base_url": "http://x", "api_key": "k"},
                            "models": {
                                "gpt-5.5": {
                                    "name": "gpt-5.5",
                                    "reasoning_effort_levels": ["low", "high"],
                                    "reasoning_effort": "high",
                                }
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        options = Settings.load_config().get_request_options("gpt-5.5", "gw")

        assert "reasoning_effort_levels" not in options
        assert options["reasoning_effort"] == "high"
