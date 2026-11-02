"""Connecting a provider discovers its models without writing them into config.

Config is what the user chose; the catalogue is what the provider said. A
discovered id must be selectable straight away and must vanish from the list
when its provider does, and a configured entry must win over the snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nova.registry import catalogue as model_catalogue
from nova.registry.discovery import DiscoveryError
from nova.server import routers
from nova.server.app import create_app
from nova.settings import Settings


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "server": {"port": 8765},
                "providers": {
                    "openai": {
                        "type": "openai-compatible",
                        "name": "OpenAI",
                        "options": {"base_url": "https://api.example.com/v1"},
                        "models": {
                            # Pinned by hand: label, tools off, explicit window.
                            "gpt-pinned": {
                                "name": "GPT Pinned",
                                "tools": False,
                                "limit": {"context": 8192},
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _settings(home: Path) -> Settings:
    return Settings.load_config()


def _models(client: TestClient) -> dict[str, dict]:
    response = client.get("/api/models")
    assert response.status_code == 200
    return {item["model"]: item for item in response.json()["items"]}


def test_snapshot_survives_a_corrupt_file(home: Path) -> None:
    (home / model_catalogue.CACHE_NAME).write_text("{not json", encoding="utf-8")

    assert model_catalogue.load(_settings(home)) == {}


def test_record_replaces_one_provider_and_keeps_the_others(home: Path) -> None:
    settings = _settings(home)
    model_catalogue.record(settings, "openai", ["b-model", "a-model", "a-model"])
    model_catalogue.record(settings, "other", ["x"])

    model_catalogue.record(settings, "openai", ["c-model"])

    stored = model_catalogue.load(settings)
    assert list(stored["openai"]) == ["c-model"]
    assert list(stored["other"]) == ["x"]


def test_discovered_models_are_selectable_but_stay_out_of_config(
    home: Path, monkeypatch
) -> None:
    async def fake_discovery(**_kwargs: object) -> list[str]:
        return ["model-a", "gpt-pinned"]

    monkeypatch.setattr(routers.config, "discover_models", fake_discovery)
    client = TestClient(create_app(settings=Settings.load_config()))

    response = client.post(
        "/api/config/providers",
        json={
            "key": "gateway",
            "type": "openai-compatible",
            "name": "Gateway",
            "base_url": "https://gateway.example/v1",
            "api_key": "sk-test",
        },
    )

    assert response.status_code == 200
    assert response.json()["warning"] is None

    on_disk = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert on_disk["providers"]["gateway"]["models"] == {}

    catalogue = json.loads(
        (home / model_catalogue.CACHE_NAME).read_text(encoding="utf-8")
    )
    assert list(catalogue["gateway"]["models"]) == ["gpt-pinned", "model-a"]

    listed = _models(client)
    assert set(listed) == {"model-a", "gpt-pinned"}
    assert listed["model-a"]["provider"] == "gateway"


def test_a_pinned_entry_wins_over_the_snapshot(home: Path, monkeypatch) -> None:
    client = TestClient(create_app(settings=Settings.load_config()))
    model_catalogue.record(_settings(home), "openai", ["gpt-pinned", "only-listed"])

    listed = _models(client)

    assert listed["gpt-pinned"]["label"] == "GPT Pinned"
    assert listed["gpt-pinned"]["tools"] is False
    # Discovered but never configured: defaults, and it is still selectable.
    assert listed["only-listed"]["label"] == "only-listed"
    assert listed["only-listed"]["tools"] is True


def test_a_removed_provider_takes_its_catalogue_with_it(home: Path) -> None:
    model_catalogue.record(_settings(home), "deleted", ["orphan"])
    client = TestClient(create_app(settings=Settings.load_config()))

    assert "orphan" not in _models(client)


def test_a_provider_that_cannot_be_asked_still_exists(home: Path, monkeypatch) -> None:
    async def failing_discovery(**_kwargs: object) -> list[str]:
        raise DiscoveryError("could not reach https://gateway.example/v1/models")

    monkeypatch.setattr(routers.config, "discover_models", failing_discovery)
    client = TestClient(create_app(settings=Settings.load_config()))

    response = client.post(
        "/api/config/providers",
        json={
            "key": "gateway",
            "type": "openai-compatible",
            "name": "Gateway",
            "base_url": "https://gateway.example/v1",
            "api_key": "sk-test",
        },
    )

    assert response.status_code == 200
    assert "could not reach" in (response.json()["warning"] or "")
    assert (
        "gateway"
        in json.loads((home / "config.json").read_text(encoding="utf-8"))["providers"]
    )
    assert not (home / model_catalogue.CACHE_NAME).exists()


def test_startup_sync_only_touches_authenticated_providers(
    home: Path, monkeypatch
) -> None:
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "good": {
                        "type": "openai-compatible",
                        "options": {"base_url": "https://good.example/v1"},
                        "models": {},
                    },
                    "down": {
                        "type": "openai-compatible",
                        "options": {"base_url": "https://down.example/v1"},
                        "models": {},
                    },
                    # Hand-authored: its key lives in config.json, so the
                    # startup pass leaves it alone.
                    "custom": {
                        "type": "openai-compatible",
                        "options": {
                            "base_url": "https://custom.example/v1",
                            "api_key": "sk-inline",
                        },
                        "models": {},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (home / "credentials.json").write_text(
        json.dumps(
            {
                "providers": {
                    "good": {"api_key": "sk-good"},
                    "down": {"api_key": "sk-down"},
                }
            }
        ),
        encoding="utf-8",
    )

    async def fake_discovery(**kwargs: object) -> list[str]:
        if "down.example" in str(kwargs.get("base_url")):
            raise DiscoveryError("could not reach https://down.example/v1/models")
        return ["fresh-model"]

    monkeypatch.setattr(routers.config, "discover_models", fake_discovery)
    client = TestClient(create_app(settings=Settings.load_config()))

    response = client.post("/api/providers/sync-models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["synced"] == ["good"]
    assert "could not reach" in payload["failed"]["down"]
    # Neither synced nor reported: it was never in scope.
    assert "custom" not in payload["failed"]
    # One provider being down must not cost the other its refresh.
    assert _models(client)["fresh-model"]["provider"] == "good"


def test_each_provider_is_one_contiguous_block(home: Path, monkeypatch) -> None:
    """The pickers draw a header per group change; scattered rows repeat it.

    Configured models used to be emitted for every provider first, then the
    discovered ones in a second pass, so a provider with both got two blocks and
    the UI showed its name twice.
    """
    from nova.registry import catalogue as catalogue_module
    from nova.server.routers.config import build_model_list_response

    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "alpha": {
                        "type": "openai-compatible",
                        "name": "Alpha",
                        "options": {"base_url": "https://alpha.example/v1"},
                        "models": {"pinned": {"name": "Pinned", "tools": True}},
                    },
                    "beta": {
                        "type": "openai-compatible",
                        "name": "Beta",
                        "options": {"base_url": "https://beta.example/v1"},
                        "models": {},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        catalogue_module,
        "load",
        lambda _settings: {
            "alpha": {"found": {}},
            "beta": {"b1": {}, "b2": {}},
        },
    )

    items = build_model_list_response(_settings(home)).items
    order = [item.provider for item in items]

    assert order == ["alpha", "alpha", "beta", "beta"], order


def test_deleting_a_provider_forgets_its_catalogue(home: Path) -> None:
    """Otherwise re-connecting the same key shows yesterday's models first."""
    from nova.config.service import ConfigService
    from nova.registry import catalogue as catalogue_module

    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "gateway": {
                        "type": "openai-compatible",
                        "options": {"base_url": "https://gateway.example/v1"},
                        "models": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    settings = _settings(home)
    catalogue_module.record(settings, "gateway", ["m1", "m2"])

    ConfigService(settings).delete_provider("gateway")

    assert "gateway" not in catalogue_module.load(_settings(home))


def test_the_provider_list_says_which_ones_are_authenticated(home: Path) -> None:
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "custom": {
                        "type": "openai-compatible",
                        "options": {
                            "base_url": "https://custom.example/v1",
                            "api_key": "sk-inline",
                        },
                        "models": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (home / "credentials.json").write_text(
        json.dumps({"providers": {"openai": {"api_key": "sk-stored"}}}),
        encoding="utf-8",
    )
    client = TestClient(create_app(settings=Settings.load_config()))

    rows = {item["key"]: item for item in client.get("/api/providers").json()["items"]}

    assert rows["openai"]["authenticated"] is True
    # It has a key, but the key is part of the author's config, not something
    # Nova stores for the machine.
    assert rows["custom"]["authenticated"] is False
    assert rows["custom"]["has_api_key"] is True


def test_the_context_a_provider_states_is_used_without_touching_config(
    home: Path, monkeypatch
) -> None:
    """Facts belong in the snapshot; config is only for overriding them."""
    from nova.llm.tokenizer import resolve_context_window
    from nova.registry import catalogue as catalogue_module
    from nova.registry.discovery import DiscoveredModel

    (home / "config.json").write_text('{"providers": {}}', encoding="utf-8")
    (home / "credentials.json").write_text(
        json.dumps({"providers": {"openai": {"api_key": "sk"}}}), encoding="utf-8"
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    from nova.settings import get_settings

    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None

    settings = Settings.load_config()
    catalogue_module.record(
        settings,
        "openai",
        [
            DiscoveredModel(id="big-model", context=1048576),
            DiscoveredModel(id="small-model"),
        ],
    )

    # A model whose name says nothing to the family table still gets the
    # provider's own number.
    assert resolve_context_window("big-model", "openai") == (1048576, "provider")
    # Nothing stated and nothing known: the default still applies.
    assert resolve_context_window("small-model", "openai")[1] == "default"


def test_models_dev_fills_gaps_without_overwriting_the_provider(home: Path) -> None:
    """One snapshot, two sources: the provider's own word outranks the catalogue."""
    from nova.registry.catalogue import load, merge_models_dev, record
    from nova.registry.discovery import DiscoveredModel

    settings = _settings(home)
    record(settings, "openai", [DiscoveredModel(id="m1", context=8192)])

    merge_models_dev(
        settings,
        {
            "openai": {
                "models": {
                    "m1": {
                        "limit": {"context": 999},
                        "reasoning": True,
                        "reasoning_options": [
                            {"type": "effort", "values": ["low", "high"]}
                        ],
                    },
                    "m2": {"limit": {"context": 1000000}},
                }
            }
        },
    )

    stored = load(Settings.load_config())["openai"]
    assert stored["m1"]["limit"]["context"] == 8192
    assert stored["m1"]["_context_source"] == "provider"
    # The catalogue supplies what the provider was silent about.
    assert stored["m1"]["reasoning_effort_levels"] == ["low", "high"]
    # And a model the provider never listed only gets cobbled-in specs if Nova
    # already knows the id.
    assert "m2" not in stored


def test_re_asking_a_provider_keeps_what_the_catalogue_added(home: Path) -> None:
    from nova.registry.catalogue import load, merge_models_dev, record
    from nova.registry.discovery import DiscoveredModel

    settings = _settings(home)
    record(settings, "openai", [DiscoveredModel(id="m1")])
    merge_models_dev(
        settings,
        {
            "openai": {
                "models": {
                    "m1": {
                        "reasoning": True,
                        "reasoning_options": [{"type": "effort", "values": ["low"]}],
                    }
                }
            }
        },
    )
    record(_settings(home), "openai", [DiscoveredModel(id="m1")])

    assert load(Settings.load_config())["openai"]["m1"]["reasoning_effort_levels"] == [
        "low"
    ]


def test_a_model_the_catalogue_calls_unusable_is_hidden(
    home: Path, monkeypatch
) -> None:
    """A deprecated or non-text model is not offered, but a pinned one survives."""
    from nova.registry import catalogue as catalogue_module
    from nova.registry.catalogue import merge_models_dev
    from nova.server.routers.config import build_model_list_response

    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "type": "openai-compatible",
                        "name": "OpenAI",
                        "options": {"base_url": "https://api.example.com/v1"},
                        # Pinned by hand: the catalogue must not hide it.
                        "models": {"old-pinned": {"name": "Old Pinned"}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    settings = _settings(home)
    catalogue_module.record(
        settings,
        "openai",
        ["old-pinned", "gone", "picture-only", "fine"],
    )

    merge_models_dev(
        settings,
        {
            "openai": {
                "models": {
                    "old-pinned": {"status": "deprecated"},
                    "gone": {"status": "deprecated"},
                    "picture-only": {"modalities": {"output": ["image"]}},
                    "fine": {"modalities": {"output": ["text"]}},
                }
            }
        },
    )

    listed = {item.model for item in build_model_list_response(_settings(home)).items}

    assert listed == {"old-pinned", "fine"}


def test_a_failed_registry_refresh_does_not_stop_the_server(
    home: Path, monkeypatch
) -> None:
    """The refresh is a nicety; the API has to come up regardless."""
    from nova.server import app as app_module

    async def explode(_settings: object) -> int:
        raise RuntimeError("models.dev is down")

    monkeypatch.setattr(app_module, "_refresh_registry_quietly", explode)
    client = TestClient(create_app(settings=Settings.load_config()))

    assert client.get("/health").status_code == 200


def test_config_wins_on_every_layer_it_can_reach(home: Path, monkeypatch) -> None:
    """One test, four fields: what the file says beats what was discovered.

    A catalogue is a snapshot of somebody else's claim; config.json is the
    operator's decision. If these ever disagree, the file has to win.
    """
    from nova.llm.reasoning import resolve_effort_levels
    from nova.llm.tokenizer import resolve_context_window
    from nova.registry import catalogue as catalogue_module
    from nova.server.routers.config import build_model_list_response

    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "type": "openai-compatible",
                        "name": "OpenAI",
                        "options": {"base_url": "https://api.example.com/v1"},
                        "models": {
                            "shared": {
                                "name": "Pinned Label",
                                "tools": False,
                                "limit": {"context": 4096},
                                "reasoning_effort_levels": ["low", "high"],
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    settings = _settings(home)

    # Discovery and the catalogue both claim something different.
    catalogue_module.record(settings, "openai", ["shared"])
    catalogue_module.merge_models_dev(
        settings,
        {
            "openai": {
                "models": {
                    "shared": {
                        "limit": {"context": 1000000},
                        "reasoning": True,
                        "reasoning_options": [
                            {"type": "effort", "values": ["minimal", "medium", "max"]}
                        ],
                    }
                }
            }
        },
    )

    refreshed = _settings(home)
    provider = refreshed.providers["openai"]
    model_config = provider.models["shared"]
    row = next(
        item
        for item in build_model_list_response(refreshed).items
        if item.model == "shared"
    )

    assert row.label == "Pinned Label"  # not "shared"
    assert row.tools is False  # not the catalogue default
    assert resolve_context_window("shared", "openai") == (4096, "config")
    assert resolve_effort_levels("shared", provider.type, model_config) == [
        "low",
        "high",
    ]


def test_a_rejected_key_does_not_create_a_provider(home: Path, monkeypatch) -> None:
    """A key the provider refuses is a definite no, not a warning.

    Saving it first would leave a broken provider behind, which the user then
    has to find and delete — the connect action has to fail as a whole.
    """

    async def reject(**_kwargs: object) -> list[str]:
        raise DiscoveryError(
            "https://gateway.example/v1/models rejected the key", status=401
        )

    monkeypatch.setattr(routers.config, "discover_models", reject)
    client = TestClient(create_app(settings=Settings.load_config()))

    response = client.post(
        "/api/config/providers",
        json={
            "key": "deepseek",
            "type": "openai-compatible",
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-wrong",
        },
    )

    assert response.status_code == 401
    assert "rejected" in response.json()["detail"]
    on_disk = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert "deepseek" not in on_disk["providers"]
    assert not (home / "credentials.json").exists()


def test_an_unreachable_provider_still_saves(home: Path, monkeypatch) -> None:
    """No answer is not a rejection: a local runtime may simply be off."""

    async def unreachable(**_kwargs: object) -> list[str]:
        raise DiscoveryError("could not reach http://localhost:11434/api/tags")

    monkeypatch.setattr(routers.config, "discover_models", unreachable)
    client = TestClient(create_app(settings=Settings.load_config()))

    response = client.post(
        "/api/config/providers",
        json={
            "key": "ollama",
            "type": "ollama",
            "name": "Ollama (local)",
            "base_url": "http://localhost:11434",
            "api_key": "",
        },
    )

    assert response.status_code == 200
    assert "could not reach" in (response.json()["warning"] or "")
    on_disk = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert "ollama" in on_disk["providers"]


def test_a_model_can_speak_a_different_transport_than_its_provider(
    home: Path, monkeypatch
) -> None:
    """opencode-go serves most models over Chat Completions and some over
    Responses; the model's own row decides, not the provider's."""
    from nova.app import runtime as runtime_module
    from nova.registry import catalogue as catalogue_module
    from nova.registry.catalogue import merge_models_dev, record

    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "gateway": {
                        "type": "openai-compatible",
                        "name": "Gateway",
                        "options": {
                            "base_url": "https://gw.example/v1",
                            "api_key": "sk",
                        },
                        "models": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    settings = _settings(home)
    record(settings, "gateway", ["plain", "luna"])
    merge_models_dev(
        settings,
        {
            "gateway": {
                "npm": "@ai-sdk/openai-compatible",
                "api": "https://gw.example/v1",
                "models": {
                    "plain": {"limit": {"context": 1000}},
                    "luna": {
                        "limit": {"context": 2000},
                        "provider": {
                            "npm": "@ai-sdk/openai",
                            "api": "https://gw.example/responses",
                        },
                    },
                },
            }
        },
    )

    stored = catalogue_module.load(_settings(home))["gateway"]
    assert stored["luna"]["type"] == "openai-response"
    assert stored["luna"]["base_url"] == "https://gw.example/responses"
    # The common case stays quiet: no per-model route recorded.
    assert "type" not in stored["plain"]

    monkeypatch.setattr(runtime_module, "get_settings", lambda: _settings(home))
    runtime_module._llm_cache.clear()

    plain = runtime_module.build_llm(provider="gateway", model="plain")
    luna = runtime_module.build_llm(provider="gateway", model="luna")

    assert type(plain).__name__ == "OpenAIProvider"
    assert plain.base_url == "https://gw.example/v1"
    assert type(luna).__name__ == "OpenAIResponsesProvider"
    assert luna.base_url == "https://gw.example/responses"


def test_connect_options_are_saved_and_used_by_the_probe(
    home: Path, monkeypatch
) -> None:
    """A gateway that fingerprints clients needs its identity on every request."""
    seen: dict[str, object] = {}

    async def probe(**kwargs: object) -> list[str]:
        seen.update(kwargs)
        return ["m1"]

    monkeypatch.setattr(routers.config, "discover_models", probe)
    client = TestClient(create_app(settings=Settings.load_config()))

    response = client.post(
        "/api/config/providers",
        json={
            "key": "gateway",
            "type": "openai-compatible",
            "name": "Gateway",
            "base_url": "https://gw.example/v1",
            "api_key": "sk",
            "options": {"user_agent": "claude-cli/2.0.0 (external, cli)"},
        },
    )

    assert response.status_code == 200
    assert seen["user_agent"] == "claude-cli/2.0.0 (external, cli)"
    # Explicit options make this a config entry, not a key with preset transport.
    entry = json.loads((home / "config.json").read_text(encoding="utf-8"))["providers"][
        "gateway"
    ]
    assert entry["options"]["user_agent"] == "claude-cli/2.0.0 (external, cli)"
    assert entry["options"]["base_url"] == "https://gw.example/v1"


def test_a_recorded_provider_is_enriched_without_another_download(
    home: Path, monkeypatch
) -> None:
    """The download and the row it describes happen at different times.

    A process fetches models.dev at startup; the provider is connected minutes
    later. The merge can only fill rows that exist, so recording has to fold in
    the catalogue already in hand — and it must do so without fetching again,
    since a second 6 MB parse leaves memory the allocator never takes back.
    """
    import asyncio

    import httpx

    from nova.registry import presets as presets_module
    from nova.registry.catalogue import load, record, refresh_models_dev

    catalog = {
        "gateway": {
            "name": "Gateway",
            "api": "https://gw.example/v1",
            "npm": "@ai-sdk/openai-compatible",
            "models": {
                "luna": {
                    "limit": {"context": 2000},
                    "provider": {"npm": "@ai-sdk/openai"},
                }
            },
        }
    }
    downloads = {"n": 0}

    class _Client:
        async def get(self, *_args: object, **_kwargs: object) -> httpx.Response:
            downloads["n"] += 1
            return httpx.Response(200, json=catalog)

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("httpx.AsyncClient", lambda **_kwargs: _Client())
    presets_module.set_candidates(())
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "gateway": {
                        "type": "openai-compatible",
                        "name": "Gateway",
                        "options": {"base_url": "https://gw.example/v1"},
                        "models": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    settings = Settings.load_config()

    # The startup download has nothing to fill yet.
    assert asyncio.run(refresh_models_dev(settings)) == 0
    assert load(settings) == {}

    record(settings, "gateway", ["luna"])

    facts = load(settings)["gateway"]["luna"]
    assert facts["limit"]["context"] == 2000
    assert facts["type"] == "openai-response"

    # One fetch for the whole session: the TTL applies again now that a merge
    # has happened, and the next provider needs no download either.
    assert asyncio.run(refresh_models_dev(settings)) == 0
    assert downloads["n"] == 1
    presets_module.set_candidates(())


def test_an_unchanged_catalogue_is_never_parsed_twice(home: Path, monkeypatch) -> None:
    """Parsing 6 MB of catalogue costs memory the allocator never returns.

    A refresh whose payload is byte-identical to the copy in hand has nothing to
    re-parse, so it must not: the merge runs, the parse does not.
    """
    import asyncio

    import httpx

    from nova.registry import catalogue as catalogue_module
    from nova.registry import presets as presets_module

    catalog = {
        "gateway": {
            "name": "Gateway",
            "api": "https://gw.example/v1",
            "npm": "@ai-sdk/openai-compatible",
            "models": {"luna": {"limit": {"context": 2000}}},
        }
    }

    class _Client:
        async def get(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return httpx.Response(200, json=catalog)

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("httpx.AsyncClient", lambda **_kwargs: _Client())
    presets_module.set_candidates(())
    settings = Settings.load_config()

    assert asyncio.run(catalogue_module.refresh_models_dev(settings)) == 0
    kept = catalogue_module._download
    assert kept is not None

    assert asyncio.run(catalogue_module.refresh_models_dev(settings, force=True)) == 0
    assert catalogue_module._download is kept
    presets_module.set_candidates(())


def test_a_custom_endpoint_is_declared_not_polled(home: Path, monkeypatch) -> None:
    """Custom means the user's own endpoint: no probe, no sync, no preset row.

    The key is a machine secret, so it goes where secrets go, and the model list
    is the declaration rather than something Nova reads off the endpoint.
    """
    probed: list[dict[str, object]] = []

    async def probe(**kwargs: object) -> list[str]:
        probed.append(kwargs)
        return ["invented"]

    monkeypatch.setattr(routers.config, "discover_models", probe)
    client = TestClient(create_app(settings=Settings.load_config()))

    response = client.post(
        "/api/config/providers",
        json={
            "key": "my-gw",
            "type": "openai-compatible",
            "name": "my-gw",
            "base_url": "https://gw.example/v1",
            "api_key": "sk-custom",
            "custom": True,
        },
    )

    assert response.status_code == 200
    assert probed == []

    entry = json.loads((home / "config.json").read_text(encoding="utf-8"))["providers"][
        "my-gw"
    ]
    assert entry["custom"] is True
    assert "api_key" not in entry["options"]
    credentials = json.loads((home / "credentials.json").read_text(encoding="utf-8"))
    assert credentials["providers"]["my-gw"]["api_key"] == "sk-custom"
    # Loaded like any other provider: the key comes back from the store.
    assert Settings.load_config().providers["my-gw"].options["api_key"] == "sk-custom"

    # Neither sync path touches it.
    assert client.post("/api/providers/sync-models").json()["synced"] == []
    assert probed == []
    assert client.post("/api/config/providers/my-gw/sync-models").status_code == 400
    assert probed == []

    # The connect form still lists it, marked as what it is.
    rows = client.get("/api/providers/presets").json()["items"]
    row = next(item for item in rows if item["id"] == "my-gw")
    assert row["custom"] is True
    assert row["base_url"] == "https://gw.example/v1"
    assert row["key_env"] is None

    # And it is not remembered as a vendor: the cache may not exist at all,
    # which is the strongest form of the same statement.
    cache = home / "provider_presets.cache.json"
    remembered = (
        json.loads(cache.read_text(encoding="utf-8"))["presets"]
        if cache.exists()
        else []
    )
    assert "my-gw" not in {item["id"] for item in remembered}


def test_rotating_a_key_keeps_it_out_of_config(home: Path) -> None:
    """A key typed into the connect screen must never land in config.json."""
    client = TestClient(create_app(settings=Settings.load_config()))
    client.post(
        "/api/config/providers",
        json={
            "key": "my-gw",
            "type": "openai-compatible",
            "name": "my-gw",
            "base_url": "https://gw.example/v1",
            "api_key": "sk-first",
            "custom": True,
        },
    )

    response = client.post(
        "/api/config/providers/update",
        json={"key": "my-gw", "api_key": "sk-second"},
    )

    assert response.status_code == 200
    entry = json.loads((home / "config.json").read_text(encoding="utf-8"))["providers"][
        "my-gw"
    ]
    assert "api_key" not in entry["options"]
    credentials = json.loads((home / "credentials.json").read_text(encoding="utf-8"))
    assert credentials["providers"]["my-gw"]["api_key"] == "sk-second"
