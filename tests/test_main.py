import sys

import nova.__main__ as nova_main


def test_main_defaults_to_cli(monkeypatch):
    called = {}

    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-main")
    monkeypatch.setattr(
        nova_main,
        "run_cli",
        lambda provider, model, settings: called.update(
            {"provider": provider, "model": model, "settings": settings}
        ),
    )
    monkeypatch.setattr(nova_main.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(sys, "argv", ["nova"])

    nova_main.main()

    assert called["provider"] == called["settings"].provider
    assert called["model"] is None


def test_main_accepts_cli_mode_argument(monkeypatch):
    called = {}

    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-main-cli")
    monkeypatch.setattr(
        nova_main,
        "run_cli",
        lambda provider, model, settings: called.update(
            {"provider": provider, "model": model, "settings": settings}
        ),
    )
    monkeypatch.setattr(nova_main.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(
        sys,
        "argv",
        ["nova", "cli", "--provider", "openai", "--model", "gpt-4o"],
    )

    nova_main.main()

    assert called["provider"] == "openai"
    assert called["model"] == "gpt-4o"
