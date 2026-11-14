"""Startup refuses to listen beyond loopback without credentials.

The API is public by default only on this machine; the moment ``host`` names a
network interface, the same routes are reachable by anyone on the LAN. These tests
pin the refusal at the one place every server configuration passes through
(``build_uvicorn_config``, used by ``nova serve``, ``nova web`` and the desktop
window), so a new entry point cannot skip it by accident.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI

from nova.server.app import build_uvicorn_config
from nova.server.auth import (
    UnsafeBindError,
    assert_safe_bind,
    is_loopback_bind,
)
from nova.settings import Settings

CREDENTIALS = ("nova", "s3cret")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", " LOCALHOST "])
def test_loopback_binds_need_no_credentials(host):
    assert is_loopback_bind(host)
    assert_safe_bind(host, None)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "nova.lan"])
def test_network_binds_without_credentials_are_refused(host):
    with pytest.raises(UnsafeBindError) as raised:
        assert_safe_bind(host, None)

    message = str(raised.value)
    assert repr(host) in message
    assert "server.auth_user" in message


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20"])
def test_network_binds_with_credentials_are_allowed(host):
    assert_safe_bind(host, CREDENTIALS)


def _settings(monkeypatch, tmp_path, server: dict) -> Settings:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps({"providers": {}, "server": server}), encoding="utf-8"
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    return Settings.load_config()


def test_the_uvicorn_config_is_refused_for_an_exposed_host(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path, {"host": "0.0.0.0"})

    with pytest.raises(UnsafeBindError):
        build_uvicorn_config(FastAPI(), settings)


def test_the_uvicorn_config_is_built_once_credentials_are_set(monkeypatch, tmp_path):
    settings = _settings(
        monkeypatch,
        tmp_path,
        {"host": "0.0.0.0", "auth_user": "nova", "auth_password": "s3cret"},
    )

    config = build_uvicorn_config(FastAPI(), settings)

    assert config.host == "0.0.0.0"


def test_the_default_host_is_loopback_and_needs_nothing(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path, {})

    config = build_uvicorn_config(FastAPI(), settings)

    assert config.host == "127.0.0.1"


def test_the_configured_port_is_used_when_none_is_given(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path, {"port": 8794})

    config = build_uvicorn_config(FastAPI(), settings)

    assert config.port == 8794


def test_a_given_port_overrides_the_configured_one(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path, {"port": 8794})

    config = build_uvicorn_config(FastAPI(), settings, port=51999)

    assert config.port == 51999
