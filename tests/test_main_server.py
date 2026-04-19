import json
import sys

import nova.__main__ as nova_main


def _write_config(home, payload):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_main_dispatches_serve_mode(monkeypatch, tmp_path):
    called = {}
    home = tmp_path / "nova-main-serve"
    _write_config(
        home,
        {
            "model": "gemma4:26b",
            "model_provider": "ollama",
            "providers": {
                "ollama": {
                    "type": "ollama",
                    "name": "Ollama (local)",
                    "options": {
                        "base_url": "http://localhost:11434",
                    },
                    "models": {
                        "gemma4:26b": {
                            "name": "gemma4:26b",
                            "tools": True,
                        }
                    },
                }
            },
        },
    )

    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setattr(
        nova_main,
        "run_server",
        lambda settings: called.update({"settings": settings}),
    )
    monkeypatch.setattr(nova_main.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(sys, "argv", ["nova", "serve"])

    nova_main.main()

    assert called["settings"].backend_port == called["settings"].backend_port


def test_main_dispatches_serve_mode_with_effective_settings(monkeypatch, tmp_path):
    called = {}
    home = tmp_path / "nova-main-serve-effective"
    _write_config(
        home,
        {
            "model": "gpt-5.4",
            "model_provider": "wbz",
            "providers": {
                "wbz": {
                    "type": "openai-compatible",
                    "name": "wbz",
                    "options": {
                        "base_url": "http://openai.local/v1",
                    },
                    "models": {
                        "gpt-5.4": {
                            "name": "gpt-5.4",
                            "tools": True,
                        }
                    },
                },
                "ollama": {
                    "type": "ollama",
                    "name": "Ollama (local)",
                    "options": {
                        "base_url": "http://localhost:11434",
                    },
                    "models": {
                        "gemma4:26b": {
                            "name": "gemma4:26b",
                            "tools": True,
                        }
                    },
                },
            },
        },
    )

    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setattr(
        nova_main,
        "run_server",
        lambda settings: called.update({"settings": settings}),
    )
    monkeypatch.setattr(nova_main.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(
        sys,
        "argv",
        ["nova", "serve", "--provider", "wbz", "--model", "gpt-5.4"],
    )

    nova_main.main()

    assert called["settings"].provider == "wbz"
    assert called["settings"].model == "gpt-5.4"


def test_main_serve_mode_skips_cli(monkeypatch, tmp_path):
    home = tmp_path / "nova-main-serve-skip"
    _write_config(
        home,
        {
            "model": "gemma4:26b",
            "model_provider": "ollama",
            "providers": {
                "ollama": {
                    "type": "ollama",
                    "name": "Ollama (local)",
                    "options": {
                        "base_url": "http://localhost:11434",
                    },
                    "models": {
                        "gemma4:26b": {
                            "name": "gemma4:26b",
                            "tools": True,
                        }
                    },
                }
            },
        },
    )

    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setattr(nova_main, "run_server", lambda settings: None)
    monkeypatch.setattr(
        nova_main,
        "run_cli",
        lambda settings: (_ for _ in ()).throw(AssertionError("run_cli should not be called")),
    )
    monkeypatch.setattr(nova_main.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(sys, "argv", ["nova", "serve"])

    nova_main.main()
