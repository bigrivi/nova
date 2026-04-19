import sys

import nova.__main__ as nova_main


def test_main_defaults_to_cli(monkeypatch):
    called = {}

    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-main")
    monkeypatch.setattr(
        nova_main,
        "run_cli",
        lambda settings: called.update({"settings": settings}),
    )
    monkeypatch.setattr(nova_main.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(sys, "argv", ["nova"])

    nova_main.main()

    assert called["settings"].provider == "ollama"
    assert called["settings"].model == "gemma4:26b"


def test_main_accepts_cli_mode_argument(monkeypatch):
    called = {}

    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-main-cli")
    monkeypatch.setattr(
        nova_main,
        "run_cli",
        lambda settings: called.update({"settings": settings}),
    )
    monkeypatch.setattr(nova_main.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(
        sys,
        "argv",
        ["nova", "cli", "--provider", "openai", "--model", "gpt-4o"],
    )

    nova_main.main()

    assert called["settings"].provider == "openai"
    assert called["settings"].model == "gpt-4o"
