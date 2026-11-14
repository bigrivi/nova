"""Which provider and model a turn runs on.

A turn's route comes from three places, in order: what the request asked for,
what the session was last run with, and what the agent record names. A source
that names a provider which is not configured is no source at all — it used to
win every other tier and then fail with "Unsupported provider", which reads
like Nova is broken rather than like the provider is gone.
"""

from __future__ import annotations

import json

import pytest

from nova.app.runtime import resolve_route
from nova.settings import Settings


@pytest.fixture
def settings_factory(monkeypatch, tmp_path):
    """Settings with the given providers, each serving a model of its own."""

    def build(*keys: str) -> Settings:
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        payload = {
            "providers": {
                key: {
                    "type": "openai-compatible",
                    "name": key,
                    "options": {"base_url": "http://127.0.0.1:1/v1", "api_key": "k"},
                    "models": {f"{key}-model": {"name": f"{key}-model"}},
                }
                for key in keys
            }
        }
        (home / "config.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        monkeypatch.setenv("NOVA_HOME", str(home))
        return Settings.load_config()

    return build


def test_the_request_wins(settings_factory):
    settings = settings_factory("first", "second")

    provider, model = resolve_route(
        settings,
        (
            ("second", "second-model"),
            ("first", "first-model"),
            ("first", "first-model"),
        ),
    )

    assert (provider, model) == ("second", "second-model")


def test_a_route_to_a_provider_that_is_gone_is_no_route(settings_factory):
    settings = settings_factory("first")

    provider, model = resolve_route(
        settings,
        (
            ("", ""),
            ("deleted-provider", "its-model"),
            ("also-deleted", "another-model"),
        ),
    )

    assert provider == "first"
    assert model == "first-model"


def test_a_session_keeps_its_route_when_the_provider_is_configured(
    settings_factory,
):
    settings = settings_factory("first", "second")

    provider, model = resolve_route(
        settings,
        (
            ("", ""),
            ("second", "second-model"),
            ("first", "first-model"),
        ),
    )

    assert (provider, model) == ("second", "second-model")


def test_a_model_is_never_paired_with_another_providers_model(settings_factory):
    """The tiers are pairs: a provider from one and a model from another asks
    a provider for a model it does not serve."""
    settings = settings_factory("first", "second")

    provider, model = resolve_route(
        settings,
        (
            ("second", ""),
            ("first", "first-model"),
        ),
    )

    assert provider == "second"
    # The model comes from the provider that was picked, not from the tier
    # below it.
    assert model == "second-model"


def test_an_agent_with_no_route_runs_on_the_first_configured_provider(
    settings_factory,
):
    settings = settings_factory("first")

    provider, model = resolve_route(settings, (("", ""), ("", ""), ("", "")))

    assert provider == "first"
    assert model == "first-model"


def test_nothing_configured_leaves_the_route_empty(settings_factory):
    settings = settings_factory()

    provider, model = resolve_route(settings, (("", ""),))

    assert (provider, model) == ("", "")
