import sys

import pytest

import nova.__main__ as nova_main


def test_main_dispatches_serve_mode(monkeypatch):
    called = {}

    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-main-serve")
    monkeypatch.setattr(
        nova_main,
        "run_server",
        lambda settings: called.update({"settings": settings}),
    )
    monkeypatch.setattr(nova_main.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(sys, "argv", ["nova", "serve"])

    nova_main.main()

    assert called["settings"].backend_port == called["settings"].backend_port


def test_main_serve_mode_skips_cli(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-main-serve-skip")
    monkeypatch.setattr(nova_main, "run_server", lambda settings: None)
    monkeypatch.setattr(
        nova_main,
        "run_cli",
        lambda provider, model, settings: (_ for _ in ()).throw(AssertionError("run_cli should not be called")),
    )
    monkeypatch.setattr(nova_main.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(sys, "argv", ["nova", "serve"])

    nova_main.main()
