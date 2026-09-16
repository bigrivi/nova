import json
import sys

import nova.__main__ as nova_main
from nova.desktop import main as desktop_main


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


def test_main_web_serves_built_frontend(monkeypatch, tmp_path):
    called: dict = {}
    ran: dict = {}
    home = tmp_path / "nova-main-web"
    _write_config(
        home,
        {
            "providers": {
                "ollama": {
                    "type": "ollama",
                    "options": {"base_url": "http://localhost:11434"},
                    "models": {"gemma4:26b": {"name": "gemma4:26b", "tools": True}},
                }
            },
        },
    )
    dist = tmp_path / "frontend-dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setattr(nova_main, "_build_frontend", lambda root: dist)
    sentinel = object()
    monkeypatch.setattr(
        nova_main,
        "run_server",
        lambda **kw: called.update(kw) or sentinel,
    )
    monkeypatch.setattr(
        nova_main.asyncio, "run", lambda coro: ran.setdefault("coro", coro))
    monkeypatch.setattr(sys, "argv", ["nova", "web", "--no-open"])

    nova_main.main()

    assert ran.get("coro") is sentinel
    assert called["settings"].frontend_dist_path == dist


def test_build_frontend_reuses_existing_dist(monkeypatch, tmp_path):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("ok", encoding="utf-8")

    def boom(*args, **kwargs):
        raise AssertionError("npm must not run when dist already exists")

    monkeypatch.setattr(nova_main.subprocess, "run", boom)

    assert nova_main._build_frontend(tmp_path) == dist


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


def test_desktop_window_url_maps_wildcard_host_to_loopback():
    assert desktop_main._window_url("0.0.0.0", 8765) == "http://127.0.0.1:8765"
    assert desktop_main._window_url("::", 8765) == "http://127.0.0.1:8765"
    assert (
        desktop_main._window_url("127.0.0.1", 8765) == "http://127.0.0.1:8765"
    )
    assert (
        desktop_main._window_url("192.168.1.28", 8765)
        == "http://192.168.1.28:8765"
    )
