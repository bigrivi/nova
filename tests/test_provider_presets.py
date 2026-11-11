"""The preset table is data, so the failure mode is a typo nobody notices.

A preset with an unknown `type` would be accepted by the API and then reject
the provider at write time, with the form to blame. These pin the two rules
form depends on: every row is creatable, and every row is distinct.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from nova.config.service import _SUPPORTED_PROVIDER_TYPES
from nova.registry import presets as presets_module
from nova.registry.presets import (
    BUNDLED,
    preset_for,
    preset_from_json,
    preset_ids,
)
from nova.server.routers.config import provider_presets


def test_every_preset_uses_a_type_the_config_accepts() -> None:
    unknown = {
        preset.id: preset.type
        for preset in BUNDLED
        if preset.type not in _SUPPORTED_PROVIDER_TYPES
    }

    assert not unknown, f"presets with an unsupported type: {unknown}"


def test_preset_ids_are_unique_and_usable_as_config_keys() -> None:
    ids = preset_ids()

    assert len(ids) == len(set(ids))
    assert all(identifier == identifier.strip().lower() for identifier in ids)


def test_keyless_presets_are_the_local_ones() -> None:
    keyless = {preset.id for preset in BUNDLED if preset.key_env is None}

    assert keyless == {"ollama", "lm-studio", "vllm", "sglang"}


def test_endpoint_returns_every_preset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text('{"providers": {}}', encoding="utf-8")
    from nova.settings import Settings

    response = asyncio.run(provider_presets(Settings.load_config()))

    assert [item.id for item in response.items] == list(preset_ids())


class _FakeClient:
    def __init__(
        self, response: httpx.Response | None = None, error: Exception | None = None
    ):
        self._response = response
        self._error = error

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, _url: str) -> httpx.Response:
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _remote(rows: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"presets": rows})


def test_a_row_pointing_at_plain_http_is_refused() -> None:
    assert (
        preset_from_json(
            {
                "id": "sketchy",
                "label": "Sketchy",
                "type": "openai-compatible",
                "base_url": "http://sketchy.example/v1",
            }
        )
        is None
    )


def test_a_local_row_may_use_plain_http() -> None:
    preset = preset_from_json(
        {
            "id": "local-llm",
            "label": "Local LLM",
            "type": "openai-compatible",
            "base_url": "http://localhost:8080/v1",
        }
    )

    assert preset is not None and preset.id == "local-llm"


def test_an_unknown_wire_type_is_refused() -> None:
    assert (
        preset_from_json(
            {
                "id": "weird",
                "label": "Weird",
                "type": "grpc",
                "base_url": "https://weird.example",
            }
        )
        is None
    )


def test_a_remote_row_cannot_rewrite_a_bundled_vendor(tmp_path: Path) -> None:
    (tmp_path / presets_module.CACHE_NAME).write_text(
        json.dumps(
            {
                "fetched_at": 1,
                "presets": [
                    {
                        "id": "openai",
                        "label": "OpenAI (mirror)",
                        "type": "openai-compatible",
                        "base_url": "https://mirror.example/v1",
                    },
                    {
                        "id": "brand-new",
                        "label": "Brand New",
                        "type": "openai-compatible",
                        "base_url": "https://new.example/v1",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = {preset.id: preset for preset in presets_module.load(tmp_path)}

    assert loaded["openai"].base_url == "https://api.openai.com/v1"
    assert loaded["brand-new"].base_url == "https://new.example/v1"
    assert preset_for("brand-new", tmp_path) is not None


def test_the_bundled_floor_says_what_it_is_for() -> None:
    """The floor is local runtimes plus the two vendors nobody can derive."""
    payload = presets_module.bundled_payload()

    assert "models.dev" in payload.get("_readme", "")
    ids = set(preset_ids())
    assert {"ollama", "vllm", "sglang", "lm-studio"} <= ids
    assert {"openai", "anthropic"} <= ids
    # Every bundled row survives the same validation a derived row does.
    assert len(BUNDLED) == len(payload["presets"])


def test_a_provider_without_a_base_url_is_not_offered() -> None:
    """Without `api` the form would save something unreachable."""
    derived = presets_module.derive_from_catalog(
        {
            "reachable": {
                "name": "Reachable",
                "api": "https://reachable.example/v1",
                "env": ["REACHABLE_KEY"],
                "npm": "@ai-sdk/openai-compatible",
            },
            "sdk-only": {
                "name": "SDK Only",
                "env": ["SDK_KEY"],
                "npm": "@ai-sdk/google",
            },
        }
    )

    assert [preset.id for preset in derived] == ["reachable"]
    assert derived[0].key_env == "REACHABLE_KEY"


def test_every_sdk_package_maps_to_one_transport() -> None:
    """The whole mapping, in one table.

    `@ai-sdk/openai` is the one that is an inference rather than a fact: the SDK
    supports both wire formats, and Nova picks Responses for it. Codewhale maps
    the plain `openai` route to Chat Completions instead, so this is a decision,
    not a derivation — which is exactly why it is written down here.
    """
    cases = {
        "@ai-sdk/anthropic": "anthropic",
        "@ai-sdk/google-vertex/anthropic": "anthropic",
        "@ai-sdk/openai": "openai-response",
        "@ai-sdk/openai-compatible": "openai-compatible",
        "@ai-sdk/groq": "openai-compatible",
        "@ai-sdk/azure": "openai-compatible",
        "@openrouter/ai-sdk-provider": "openai-compatible",
        "": "openai-compatible",
        None: "openai-compatible",
    }

    for npm, expected in cases.items():
        assert presets_module.type_for_npm(npm) == expected, npm


def test_the_derived_provider_preset_uses_that_mapping() -> None:
    derived = presets_module.derive_from_catalog(
        {
            "an": {
                "name": "Anthropic-ish",
                "api": "https://an.example",
                "env": ["AN_KEY"],
                "npm": "@ai-sdk/anthropic",
            },
            "oa": {
                "name": "OpenAI-ish",
                "api": "https://oa.example/v1",
                "env": ["OA_KEY"],
                "npm": "@ai-sdk/openai-compatible",
            },
            "resp": {
                "name": "Responses-ish",
                "api": "https://resp.example/v1",
                "env": ["RESP_KEY"],
                "npm": "@ai-sdk/openai",
            },
        }
    )

    by_id = {preset.id: preset for preset in derived}
    assert by_id["an"].type == "anthropic"
    assert by_id["oa"].type == "openai-compatible"
    assert by_id["resp"].type == "openai-response"


def test_a_bundled_row_beats_a_derived_one(tmp_path: Path) -> None:
    """The floor exists to pin what a catalogue gets wrong."""
    derived = presets_module.derive_from_catalog(
        {
            "openai": {
                "name": "OpenAI (mirror)",
                "api": "https://mirror.example/v1",
                "env": ["OPENAI_API_KEY"],
                "npm": "@ai-sdk/openai",
            },
            "brand-new": {
                "name": "Brand New",
                "api": "https://new.example/v1",
                "env": ["BRAND_NEW_KEY"],
                "npm": "@ai-sdk/openai-compatible",
            },
        }
    )
    presets_module.set_candidates(derived)
    try:
        loaded = {preset.id: preset for preset in presets_module.load(tmp_path)}
    finally:
        presets_module.set_candidates(())

    assert loaded["openai"].base_url == "https://api.openai.com/v1"
    assert loaded["brand-new"].base_url == "https://new.example/v1"
    assert loaded["brand-new"].type == "openai-compatible"


def test_only_what_was_connected_is_written_to_disk(tmp_path: Path) -> None:
    """The catalogue is a suggestion list; the disk holds what you connected."""
    candidates = presets_module.derive_from_catalog(
        {
            "wanted": {
                "name": "Wanted",
                "api": "https://wanted.example/v1",
                "env": ["WANTED_KEY"],
                "npm": "@ai-sdk/openai-compatible",
            },
            "unwanted": {
                "name": "Unwanted",
                "api": "https://unwanted.example/v1",
                "env": ["UNWANTED_KEY"],
                "npm": "@ai-sdk/openai-compatible",
            },
        }
    )
    presets_module.set_candidates(candidates)
    try:
        # While the process lives, both are offered.
        assert {p.id for p in presets_module.load(tmp_path)} >= {"wanted", "unwanted"}

        wanted = next(preset for preset in candidates if preset.id == "wanted")
        presets_module.remember(tmp_path, wanted)
    finally:
        presets_module.set_candidates(())

    on_disk = presets_module.cache_path(tmp_path).read_text(encoding="utf-8")
    assert "wanted" in on_disk
    assert "unwanted" not in on_disk

    # After a restart with no refresh, the connected one still resolves.
    after_restart = {preset.id for preset in presets_module.load(tmp_path)}
    assert "wanted" in after_restart
    assert "unwanted" not in after_restart


def test_a_fresh_process_derives_even_when_the_cache_is_fresh(
    tmp_path: Path, monkeypatch
) -> None:
    """Candidates live in memory, so a TTL hit must not skip a new process.

    Without this, restarting the server showed the floor for up to a day: the
    on-disk catalogue was fresh, the in-memory list was empty, and the TTL said
    "no need to fetch".
    """
    from nova.registry import catalogue as catalogue_module
    from nova.settings import Settings

    monkeypatch.setenv("NOVA_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text('{"providers": {}}', encoding="utf-8")
    (tmp_path / "models.json").write_text(
        json.dumps({"_meta": {"models_dev_at": 2**31}, "openai": {"models": {}}}),
        encoding="utf-8",
    )

    calls = {"n": 0}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, _url):
            calls["n"] += 1
            return httpx.Response(
                200,
                json={
                    "newvendor": {
                        "name": "New Vendor",
                        "api": "https://new.example/v1",
                        "env": ["NEW_KEY"],
                        "npm": "@ai-sdk/openai-compatible",
                        "models": {},
                    }
                },
            )

    # `refresh_models_dev` imports httpx inside the call, so patch the module
    # attribute it will look up rather than the (absent) re-export.
    monkeypatch.setattr("httpx.AsyncClient", lambda **_kwargs: _Client())
    presets_module.set_candidates(())

    asyncio.run(catalogue_module.refresh_models_dev(Settings.load_config()))

    assert calls["n"] == 1
    assert "newvendor" in {preset.id for preset in presets_module.load(tmp_path)}
    presets_module.set_candidates(())
