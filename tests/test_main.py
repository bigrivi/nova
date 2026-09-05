import json
import sys

import nova.__main__ as nova_main


def _write_config(home, payload):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_main_defaults_to_serve(monkeypatch, tmp_path):
    called: dict = {}
    ran: dict = {}
    home = tmp_path / "nova-main"
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
    sentinel = object()
    monkeypatch.setattr(
        nova_main,
        "run_server",
        lambda **kw: called.update(kw) or sentinel,
    )
    monkeypatch.setattr(
        nova_main.asyncio, "run", lambda coro: ran.setdefault("coro", coro))
    monkeypatch.setattr(sys, "argv", ["nova"])

    nova_main.main()

    assert ran.get("coro") is sentinel
    assert called.get("settings") is not None


def test_main_desktop_dispatch(monkeypatch, tmp_path):
    called: dict = {}
    home = tmp_path / "nova-main-desktop"
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
        "run_desktop",
        lambda **kw: called.update(kw),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["nova", "desktop"],
    )

    nova_main.main()

    assert called.get("settings") is not None
    assert called.get("dev") is False
