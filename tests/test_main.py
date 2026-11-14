import io
import json
import sys
import time

import pytest

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
        nova_main.asyncio, "run", lambda coro: ran.setdefault("coro", coro)
    )
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
        nova_main.asyncio, "run", lambda coro: ran.setdefault("coro", coro)
    )
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


def test_main_websearch_stats_prints_a_table_and_starts_nothing(
    monkeypatch, tmp_path, capsys
):
    home = tmp_path / "nova-main-ws-stats"
    _write_config(home, {"providers": {}})
    usage = home / "logs" / "web_search_usage.jsonl"
    usage.parent.mkdir(parents=True)
    usage.write_text(
        json.dumps({"ts": time.time(), "backend": "exa", "outcome": "ok"})
        + "\n"
        + json.dumps(
            {
                "ts": time.time(),
                "backend": "keenable",
                "outcome": "rate_limited",
                "remaining": 12,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def boom(**kwargs):
        raise AssertionError("websearch-stats must not start the server")

    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setattr(nova_main, "run_server", boom)
    monkeypatch.setattr(sys, "argv", ["nova", "websearch-stats", "--days", "7"])

    nova_main.main()

    printed = capsys.readouterr().err
    assert "exa" in printed
    assert "keenable" in printed
    assert "quota_low" in printed
    assert "12" in printed


def test_main_websearch_stats_reports_an_empty_log(monkeypatch, tmp_path, capsys):
    home = tmp_path / "nova-main-ws-empty"
    _write_config(home, {"providers": {}})

    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setattr(sys, "argv", ["nova", "websearch-stats"])

    nova_main.main()

    assert "No web_search usage recorded yet" in capsys.readouterr().err


def test_version_flag_prints_the_package_version(monkeypatch, capsys):
    from nova import __version__

    monkeypatch.setattr(sys, "argv", ["nova", "-v"])

    with pytest.raises(SystemExit) as exit_info:
        nova_main.main()

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"nova {__version__}"


def test_version_long_form_matches(monkeypatch, capsys):
    from nova import __version__

    monkeypatch.setattr(sys, "argv", ["nova", "--version"])

    with pytest.raises(SystemExit):
        nova_main.main()

    assert __version__ in capsys.readouterr().out


class _FakeTty(io.StringIO):
    """A stream that claims to be a terminal."""

    def isatty(self) -> bool:
        return True


def test_bare_nova_starts_the_tui_when_a_terminal_is_attached(monkeypatch):
    started: list[str] = []
    monkeypatch.setattr(nova_main.sys, "stdin", _FakeTty())
    monkeypatch.setattr(nova_main.sys, "stdout", _FakeTty())
    monkeypatch.setattr(nova_main, "_run_tui", lambda: started.append("tui"))
    monkeypatch.setattr(nova_main.sys, "argv", ["nova"])

    nova_main.main()

    assert started == ["tui"]


def test_bare_nova_starts_the_backend_without_a_terminal(monkeypatch):
    started: list[str] = []
    monkeypatch.setattr(nova_main.sys, "argv", ["nova"])
    monkeypatch.setattr(nova_main, "run_server", lambda **kw: started.append("serve"))
    monkeypatch.setattr(
        nova_main.asyncio, "run", lambda coro: coro.close() if coro else None
    )

    nova_main.main()

    # A container entrypoint runs `nova` without a terminal; it must get the
    # backend it used to get, not a terminal UI it cannot draw.
    assert started == ["serve"]


def test_the_mode_can_still_be_named_explicitly(monkeypatch):
    started: list[str] = []
    monkeypatch.setattr(nova_main.sys, "stdin", _FakeTty())
    monkeypatch.setattr(nova_main.sys, "stdout", _FakeTty())
    monkeypatch.setattr(nova_main, "_run_tui", lambda: started.append("tui"))
    monkeypatch.setattr(nova_main, "run_server", lambda **kw: started.append("serve"))
    monkeypatch.setattr(
        nova_main.asyncio, "run", lambda coro: coro.close() if coro else None
    )
    monkeypatch.setattr(nova_main.sys, "argv", ["nova", "serve"])

    nova_main.main()

    assert started == ["serve"]


def test_main_refuses_a_port_of_zero(monkeypatch):
    # Two shared backends on port zero would both boot against the same
    # database, so the flag refuses it instead of pretending it is "any port".
    monkeypatch.setattr(sys, "argv", ["nova", "serve", "--port", "0"])

    with pytest.raises(SystemExit) as raised:
        nova_main.main()

    assert raised.value.code == 2
