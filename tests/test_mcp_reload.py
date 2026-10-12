"""Reloading MCP servers without restarting Nova.

The settings UI used to tell the user to restart, and the reason was real: a
toolset is cached under a key made of the agent, model, posture and permission
mode -- not the MCP config -- so a config change reached nothing until the
process did. Reloading therefore needs two steps that are useless apart, and
these tests hold them together:

* reconnecting the manager changes nothing while a cached registry still holds
  the old servers' tools;
* emptying the cache changes nothing while the manager is still connected to
  what it read at startup.

The wiring test at the bottom is the one that matters most, because both halves
pass their own tests while the endpoint forgets to call either.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from nova.mcp.manager import MCPManager
from nova.settings import get_settings
from nova.tools.registry import ToolRegistry


def _write_mcp_config(home, servers: dict) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps({"providers": {}, "mcp_servers": servers}), encoding="utf-8"
    )


def _server_entry(script: str) -> dict:
    return {"command": sys.executable, "args": [script]}


# ── the manager reconnects from the config as it is now ───────────────


@pytest.mark.asyncio
async def test_reload_connects_a_server_added_since_startup(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """The case the feature exists for: a first server, added while running."""
    home = tmp_path / "home"
    _write_mcp_config(home, {})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await manager.ensure_initialized()
        assert manager.load_report() == [], "nothing configured yet"

        # The user adds a server through the settings UI.
        _write_mcp_config(home, {"demo": _server_entry(mcp_server_path)})
        get_settings.cache_clear()
        await manager.reload()

        report = manager.load_report()
        assert [entry.server for entry in report] == ["demo"]
        assert report[0].loaded == 1, "the server's own tool should be loadable"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_reload_drops_a_server_removed_since_startup(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """Removal has to be as live as addition, or deleted tools stay reachable."""
    home = tmp_path / "home"
    _write_mcp_config(home, {"demo": _server_entry(mcp_server_path)})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await manager.ensure_initialized()
        assert [entry.server for entry in manager.load_report()] == ["demo"]

        _write_mcp_config(home, {})
        get_settings.cache_clear()
        await manager.reload()

        assert manager.load_report() == []
        assert manager._mcp_clients == [], "the old client should be closed and gone"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_reload_does_not_deadlock(monkeypatch, tmp_path, mcp_server_path) -> None:
    """`asyncio.Lock` is not reentrant, and `ensure_initialized` takes it.

    Reconnecting while still holding the lock is the natural way to write this
    and it hangs rather than failing, so it is pinned rather than reasoned about.
    """
    import asyncio

    home = tmp_path / "home"
    _write_mcp_config(home, {"demo": _server_entry(mcp_server_path)})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await asyncio.wait_for(manager.reload(), timeout=30)
        assert [entry.server for entry in manager.load_report()] == ["demo"]
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_reload_rebuilds_tools_under_the_same_names(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """A reload must not rename tools, or a session's cached names go stale."""
    home = tmp_path / "home"
    _write_mcp_config(home, {"demo": _server_entry(mcp_server_path)})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await manager.ensure_initialized()
        before = manager.load_report()[0].names

        await manager.reload()

        assert manager.load_report()[0].names == before
    finally:
        await manager.shutdown()


# ── the two steps are useless apart ──────────────────────────────────


@pytest.mark.asyncio
async def test_a_cached_registry_still_holds_the_old_tools(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """Why reconnecting alone is not enough.

    This is the state the cache leaves behind, and it is what the second half of
    `reload_mcp_servers` exists to clear. Asserted directly because the failure it
    describes is invisible: the new tools are simply absent, and nothing errors.
    """
    import nova.app.runtime as runtime

    home = tmp_path / "home"
    _write_mcp_config(home, {})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    # A registry cached while no server was configured, as `build_agent` leaves it.
    stale = ToolRegistry()
    runtime._registry_cache["main:model:False::ask"] = stale

    _write_mcp_config(home, {"demo": _server_entry(mcp_server_path)})
    get_settings.cache_clear()

    try:
        # Reconnecting the manager on its own leaves the cache untouched, so a
        # later agent would be handed `stale` and never see `demo`.
        assert "demo" not in json.dumps(list(stale.tools))
        assert runtime._registry_cache.get("main:model:False::ask") is stale
    finally:
        runtime._registry_cache.clear()


@pytest.mark.asyncio
async def test_reload_clears_the_cached_toolsets(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    import nova.app.runtime as runtime

    home = tmp_path / "home"
    _write_mcp_config(home, {"demo": _server_entry(mcp_server_path)})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    runtime._registry_cache["main:model:False::ask"] = ToolRegistry()
    try:
        await runtime.reload_mcp_servers()

        assert runtime._registry_cache == {}, (
            "a registry built without the new server would otherwise be reused "
            "for every later message"
        )
    finally:
        runtime._registry_cache.clear()
        await MCPManager.get_shared().shutdown()


# ── a server that cannot connect says so ─────────────────────────────
#
# A failed server has no tools, and its absence is the only symptom it has. The
# user's report is a tool that used to work and does not, with nothing to point
# at -- so the reason has to survive to the settings list.


@pytest.mark.asyncio
async def test_a_server_that_cannot_connect_is_reported_with_a_reason(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """The command is named, because 'No such file or directory' does not help."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {},
                "mcp_servers": {
                    "broken": {"command": "definitely-not-a-real-binary-xyz"}
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await manager.ensure_initialized()

        report = manager.load_report()
        assert len(report) == 1, "a broken server must not vanish from the report"
        assert report[0].server == "broken"
        assert report[0].error, "and it must say why"
        assert "definitely-not-a-real-binary-xyz" in report[0].error
        assert report[0].loaded == 0
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_a_healthy_server_reports_no_error(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """So the UI can tell "broken" from "fine" rather than from an empty string."""
    home = tmp_path / "home"
    _write_mcp_config(home, {"demo": _server_entry(mcp_server_path)})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await manager.ensure_initialized()

        assert manager.load_report()[0].error == ""
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_one_broken_server_does_not_hide_the_others(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """Connecting in parallel must not let a failure take the batch down."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {},
                "mcp_servers": {
                    "broken": {"command": "definitely-not-a-real-binary-xyz"},
                    "demo": {
                        "command": sys.executable,
                        "args": [mcp_server_path],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await manager.ensure_initialized()

        by_name = {entry.server: entry for entry in manager.load_report()}
        assert set(by_name) == {"broken", "demo"}
        assert by_name["broken"].error
        assert by_name["demo"].error == ""
        assert by_name["demo"].loaded == 1
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_a_config_with_neither_command_nor_url_is_reported(
    monkeypatch, tmp_path
) -> None:
    """A bad config is a mistake in the config, not a network fault."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps({"providers": {}, "mcp_servers": {"empty": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await manager.ensure_initialized()

        assert manager.load_report()[0].error, "should say what is missing"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_reload_recovers_a_server_that_cannot_connect_yet(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """The usual case: the server was down, and is later started.

    This is the state the feature exists for -- the fix is starting the server,
    and the reload is what has to notice.
    """
    home = tmp_path / "home"
    _write_mcp_config(home, {"demo": {"command": "definitely-not-a-real-binary-xyz"}})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await manager.ensure_initialized()
        assert manager.load_report()[0].error

        _write_mcp_config(home, {"demo": _server_entry(mcp_server_path)})
        get_settings.cache_clear()
        await manager.reload()

        entry = manager.load_report()[0]
        assert entry.error == ""
        assert entry.loaded == 1
    finally:
        await manager.shutdown()


def test_the_api_carries_the_error_to_the_ui(monkeypatch, tmp_path) -> None:
    """The reason has to survive the response, or the UI cannot show it."""
    from fastapi.testclient import TestClient

    import nova.app.runtime as runtime
    from nova.server.app import create_app

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {},
                "mcp_servers": {
                    "broken": {"command": "definitely-not-a-real-binary-xyz"}
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    client = TestClient(create_app(settings=get_settings()))
    try:
        items = client.get("/api/mcp-servers").json()["items"]

        assert len(items) == 1
        assert items[0]["name"] == "broken"
        assert items[0]["error"], "the response must carry the reason"
        assert "definitely-not-a-real-binary-xyz" in items[0]["error"]
        assert items[0]["loaded_tools"] == []
    finally:
        runtime._registry_cache.clear()
        asyncio.run(MCPManager.get_shared().shutdown())


# ── the endpoint does both, in order ─────────────────────────────────
#
# Both halves above pass while the endpoint forgets to call either, which is the
# failure this file would otherwise not catch: nothing errors, the tools are just
# absent until the next restart -- the exact behaviour being replaced.


def test_saving_a_server_reconnects_and_drops_the_cache(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """The manager is connected to the config *before* the change.

    Starting from a fresh process would prove nothing about the reconnect: the
    list response calls `ensure_initialized`, which connects when nothing is
    connected yet, so the new server would appear whether or not a reload
    happened. What the reload actually has to do is replace a connection that
    already exists -- and in a running process one always does.
    """
    from fastapi.testclient import TestClient

    import nova.app.runtime as runtime
    from nova.server.app import create_app

    home = tmp_path / "home"
    _write_mcp_config(home, {"first": _server_entry(mcp_server_path)})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager.get_shared()
    runtime._registry_cache["main:model:False::ask"] = ToolRegistry()
    client = TestClient(create_app(settings=get_settings()))

    try:
        # The process is up and connected, as any running Nova is by the time a
        # user reaches the settings dialog.
        asyncio.run(manager.ensure_initialized())
        assert [entry.server for entry in manager.load_report()] == ["first"]

        response = client.post(
            "/api/config/mcp/add",
            json={
                "name": "second",
                "command": sys.executable,
                "args": [mcp_server_path],
                "env": [],
                "url": "",
                "headers": [],
            },
        )

        assert response.status_code == 200, response.text
        # The half a caller forgets, because reconnecting "looks like" the whole
        # job.
        assert runtime._registry_cache == {}
        # The half that makes the tools appear: without a reconnect the manager
        # is still holding the one server it read at startup.
        assert sorted(entry.server for entry in manager.load_report()) == [
            "first",
            "second",
        ]
    finally:
        runtime._registry_cache.clear()
        asyncio.run(manager.shutdown())


def test_testing_a_server_does_not_reconnect(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """A test is a question, not a save.

    Reloading here would drop every cached toolset because the user pressed a
    button that promised not to change anything.
    """
    from fastapi.testclient import TestClient

    import nova.app.runtime as runtime
    from nova.server.app import create_app

    home = tmp_path / "home"
    _write_mcp_config(home, {})
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    sentinel = ToolRegistry()
    runtime._registry_cache["main:model:False::ask"] = sentinel
    client = TestClient(create_app(settings=get_settings()))

    try:
        response = client.post(
            "/api/config/mcp/test",
            json={
                "name": "demo",
                "command": sys.executable,
                "args": [mcp_server_path],
                "env": [],
                "url": "",
                "headers": [],
            },
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert runtime._registry_cache.get("main:model:False::ask") is sentinel
    finally:
        runtime._registry_cache.clear()
