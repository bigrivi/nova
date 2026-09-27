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

    def test_a_value_already_in_the_body_is_left_alone(self):
        """`setdefault` is what makes the call order the precedence.

        Applied per-turn first and to the configured default second, a default
        fills the gap rather than overruling an explicit pick; a value the caller
        put in the body directly outranks both.
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
    async def test_a_value_put_straight_in_the_options_still_wins(self, monkeypatch):
        """`setdefault` in apply_effort: the body arrived with it already set."""
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

    def test_neither_effort_key_reaches_the_payload_raw(self, tmp_path):
        """Both are internal config keys, read by name rather than forwarded.

        `reasoning_effort_levels` describes the UI and `reasoning_effort` is a
        default whose spelling differs per provider, so neither can ride the
        generic passthrough. Letting the latter through sent a flat
        `reasoning_effort` to the Responses API, which has no such field and
        answered 400.
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
        settings = Settings.load_config()

        options = settings.get_request_options("gpt-5.5", "gw")
        assert "reasoning_effort_levels" not in options
        assert "reasoning_effort" not in options
        assert settings.get_default_reasoning_effort("gpt-5.5", "gw") == "high"


class TestConfiguredDefaultReachesTheWire:
    """A level set in config.json must arrive in the provider's own spelling.

    Regression: the value used to ride the request-options passthrough, so a
    Responses-API model emitted both a flat `reasoning_effort` and a nested
    `reasoning.effort`. The flat one is an unknown parameter there and the
    provider answered 400 `unknown parameter reasoning_effort`.
    """

    @staticmethod
    def _settings(home, provider_type: str, **model):
        import json

        from nova.settings import Settings

        home.mkdir(parents=True, exist_ok=True)
        (home / "config.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "gw": {
                            "type": provider_type,
                            "name": "gw",
                            "options": {"base_url": "http://x", "api_key": "k"},
                            "models": {"m": {"name": "m", **model}},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return Settings.load_config()

    @staticmethod
    def _build(provider_type: str, per_turn, default):
        from nova.llm.openai import OpenAIProvider
        from nova.llm.openai_response import OpenAIResponsesProvider

        cls = (
            OpenAIProvider
            if provider_type == "openai-compatible"
            else OpenAIResponsesProvider
        )
        return cls(api_key="k", default_reasoning_effort=default)._build_body(
            [{"role": "user", "content": "hi"}], "m", reasoning_effort=per_turn
        )

    def test_the_responses_api_never_sees_a_flat_effort(self):
        body = self._build("openai-response", "xhigh", "high")
        assert "reasoning_effort" not in body
        assert body["reasoning"] == {"effort": "xhigh"}

    def test_chat_completions_takes_the_flat_field(self):
        body = self._build("openai-compatible", "xhigh", "high")
        assert body["reasoning_effort"] == "xhigh"
        assert "reasoning" not in body

    def test_the_per_turn_pick_outranks_the_configured_default(self):
        """A configured level is a fallback, not a ceiling.

        It is what a run uses when nothing was picked; picking one explicitly
        has to be able to go above or below it, or the control in the composer
        would be inert on every model whose config names a default.
        """
        assert (
            self._build("openai-compatible", "xhigh", "medium")["reasoning_effort"]
            == "xhigh"
        )
        assert (
            self._build("openai-response", "xhigh", "medium")["reasoning"]
            == {"effort": "xhigh"}
        )
        assert (
            self._build("openai-compatible", "low", "high")["reasoning_effort"]
            == "low"
        )

    def test_the_configured_default_applies_when_nothing_was_picked(self):
        assert (
            self._build("openai-compatible", None, "medium")["reasoning_effort"]
            == "medium"
        )
        assert self._build("openai-response", None, "medium")["reasoning"] == {
            "effort": "medium"
        }

    def test_the_per_turn_pick_applies_when_config_says_nothing(self):
        assert self._build("openai-compatible", "xhigh", None)["reasoning_effort"] == "xhigh"
        assert self._build("openai-response", "xhigh", None)["reasoning"] == {"effort": "xhigh"}

    def test_neither_leaves_the_body_without_a_level(self):
        assert "reasoning_effort" not in self._build("openai-compatible", None, None)
        assert "reasoning" not in self._build("openai-response", None, None)

    def test_end_to_end_from_config(self, monkeypatch, tmp_path):
        """The whole path, from config.json through to the request body."""
        from nova.app.runtime import build_llm

        home = tmp_path / ".nova"
        self._settings(
            home,
            "openai-response",
            reasoning_effort="high",
            reasoning_effort_levels=["minimal", "low", "medium", "high", "xhigh"],
        )
        monkeypatch.setenv("NOVA_HOME", str(home))
        from nova.settings import get_settings

        get_settings.cache_clear()
        try:
            body = build_llm(provider="gw", model="m")._build_body(
                [{"role": "user", "content": "hi"}], "m", reasoning_effort="xhigh"
            )
        finally:
            get_settings.cache_clear()

        assert "reasoning_effort" not in body
        assert body["reasoning"] == {"effort": "xhigh"}, (
            "the pick from the composer must reach the wire, not the config default"
        )

    def test_end_to_end_falls_back_to_the_configured_default(self, monkeypatch, tmp_path):
        """Same config, nothing picked: the default is what runs."""
        from nova.app.runtime import build_llm

        home = tmp_path / ".nova"
        self._settings(
            home,
            "openai-response",
            reasoning_effort="high",
            reasoning_effort_levels=["minimal", "low", "medium", "high", "xhigh"],
        )
        monkeypatch.setenv("NOVA_HOME", str(home))
        from nova.settings import get_settings

        get_settings.cache_clear()
        try:
            body = build_llm(provider="gw", model="m")._build_body(
                [{"role": "user", "content": "hi"}], "m", reasoning_effort=None
            )
        finally:
            get_settings.cache_clear()

        assert body["reasoning"] == {"effort": "high"}
