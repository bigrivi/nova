"""Editing config.json while a backend runs must reach the next request.

The TUI reuses a detached backend (``startBackend`` returns early when the port
is healthy), so a long-lived server that kept the model list it read at boot
would show a picker that has nothing to do with the file on disk. The mtime check
in ``apply_config_change`` is what closes that gap, including for requests that
never touch the config routes.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from nova.server.app import create_app
from nova.settings import get_settings, reload_settings


def _payload(*providers: str) -> dict:
    return {
        "providers": {
            name: {
                "type": "openai-compatible",
                "name": name,
                "options": {"base_url": "http://127.0.0.1:1/v1", "api_key": "x"},
                "models": {"m1": {"name": "M1"}},
            }
            for name in providers
        }
    }


@pytest.fixture
def client():
    settings = get_settings()
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client, settings


def _write(settings, *providers: str) -> None:
    settings.config_path.write_text(json.dumps(_payload(*providers)), encoding="utf-8")


def test_a_config_edit_reaches_the_next_request(client) -> None:
    http, settings = client
    assert http.get("/api/models").json()["items"] == []

    _write(settings, "acme")

    names = {provider["key"] for provider in http.get("/api/providers").json()["items"]}
    assert names == {"acme"}


def test_a_broken_config_keeps_the_last_good_settings(client) -> None:
    http, settings = client
    _write(settings, "acme")
    assert http.get("/api/providers").json()["items"]

    settings.config_path.write_text("{ not json", encoding="utf-8")

    response = http.get("/api/providers")
    assert response.status_code == 200
    assert [item["key"] for item in response.json()["items"]] == ["acme"]


def test_a_deleted_config_is_not_recreated(client) -> None:
    """A reload must not resurrect an empty default under a running process."""
    http, settings = client
    _write(settings, "acme")
    assert http.get("/api/providers").json()["items"]

    settings.config_path.unlink()

    response = http.get("/api/providers")
    assert response.status_code == 200
    assert [item["key"] for item in response.json()["items"]] == ["acme"]
    assert not settings.config_path.exists()


def test_reload_keeps_the_last_good_settings_when_the_file_is_gone() -> None:
    settings = get_settings()
    _write(settings, "acme")
    reload_settings()
    before = get_settings()
    before.config_path.unlink()

    with pytest.raises(FileNotFoundError):
        reload_settings(ensure=False)

    assert get_settings() is before, "a failed reload must not clear the cache"
    assert not before.config_path.exists(), "the default file must not come back"
