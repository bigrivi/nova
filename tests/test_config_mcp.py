"""MCP server configuration: the JSON CRUD, and the live connection probe.

Two layers, tested apart. The CRUD is a pure function of a JSON file -- no
network, no subprocess -- so it is exercised against a temp config and asserts
the shape that lands on disk, which is the shape the transport layer reads at
startup. The probe is the opposite: it only matters when it really connects, so
it runs against the same stdio test server the rest of the MCP suite uses, and
against a command that does not exist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from nova.config.service import (
    ConfigService,
    ConfigValidationError,
    McpServerConfig,
)
from nova.mcp.probe import probe_mcp_server
from nova.settings import Settings


def _service(tmp_path: Path, payload: dict | None = None) -> ConfigService:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(payload or {"providers": {}}, indent=2), encoding="utf-8"
    )
    # ConfigService reads only ``settings.config_path``; a stub keeps the test
    # off the full Settings constructor and its seven required paths.
    settings = SimpleNamespace(config_path=config_path)
    return ConfigService(cast(Settings, settings))


# ── CRUD, as a function of the JSON file ─────────────────────────────


def test_add_stdio_server_writes_the_transport_shape(tmp_path: Path) -> None:
    """What lands on disk is what create_transport reads: command/args/env."""
    service = _service(tmp_path)
    service.add_mcp_server(
        McpServerConfig(
            name="files",
            command="npx",
            args=("-y", "@modelcontextprotocol/server-filesystem"),
            env=(("ROOT", "/tmp"),),
        )
    )
    stored = service.list_mcp_servers()
    assert stored == {
        "files": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "env": {"ROOT": "/tmp"},
        }
    }


def test_add_http_server_writes_only_url_keys(tmp_path: Path) -> None:
    """A remote server carries url/headers and never a stray command key.

    create_transport decides stdio-vs-http on which key is present, so a config
    that leaked an empty command would be ambiguous.
    """
    service = _service(tmp_path)
    service.add_mcp_server(
        McpServerConfig(
            name="remote",
            url="https://example.com/mcp",
            headers=(("Authorization", "Bearer t"),),
        )
    )
    assert service.list_mcp_servers()["remote"] == {
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer t"},
    }


def test_a_server_is_either_a_command_or_a_url(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ConfigValidationError, match=r"command.*or a URL"):
        service.add_mcp_server(McpServerConfig(name="empty"))
    with pytest.raises(ConfigValidationError, match="not both"):
        service.add_mcp_server(
            McpServerConfig(name="both", command="x", url="https://y")
        )


def test_a_remote_url_must_be_http(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ConfigValidationError, match="http"):
        service.add_mcp_server(McpServerConfig(name="ws", url="ws://example.com"))


def test_add_rejects_a_duplicate_name(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.add_mcp_server(McpServerConfig(name="dup", command="x"))
    with pytest.raises(ConfigValidationError, match="already exists"):
        service.add_mcp_server(McpServerConfig(name="dup", command="y"))


def test_editing_a_command_keeps_a_secret_the_form_cannot_show(
    tmp_path: Path,
) -> None:
    """The API never returns env/header values, so an edit must not lose them.

    The settings form shows the *names* of a server's secrets and leaves their
    values blank. Replacing the config outright on save would silently delete a
    token every time someone corrected a typo in the command line.
    """
    service = _service(tmp_path)
    service.add_mcp_server(McpServerConfig(name="s", command="old", env=(("A", "1"),)))
    service.update_mcp_server(
        "s", McpServerConfig(name="s", command="new", env=(("A", ""),))
    )
    assert service.list_mcp_servers()["s"] == {
        "command": "new",
        "env": {"A": "1"},
    }


def test_a_submitted_value_overwrites_the_stored_one(tmp_path: Path) -> None:
    """Retyping a secret is how a user rotates it."""
    service = _service(tmp_path)
    service.add_mcp_server(McpServerConfig(name="s", command="c", env=(("A", "old"),)))
    service.update_mcp_server(
        "s", McpServerConfig(name="s", command="c", env=(("A", "new"),))
    )
    assert service.list_mcp_servers()["s"]["env"] == {"A": "new"}


def test_a_new_secret_is_added_and_a_dropped_row_is_removed(tmp_path: Path) -> None:
    """Two rows the form *can* show, told apart by whether they were submitted."""
    service = _service(tmp_path)
    service.add_mcp_server(
        McpServerConfig(name="s", command="c", env=(("KEEP", "1"), ("DROP", "2")))
    )
    service.update_mcp_server(
        "s",
        McpServerConfig(name="s", command="c", env=(("KEEP", ""), ("ADD", "3"))),
    )
    assert service.list_mcp_servers()["s"]["env"] == {"KEEP": "1", "ADD": "3"}


def test_headers_merge_the_same_way_env_does(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.add_mcp_server(
        McpServerConfig(
            name="remote",
            url="https://example.com/mcp",
            headers=(("Authorization", "Bearer old"),),
        )
    )
    service.update_mcp_server(
        "remote",
        McpServerConfig(
            name="remote",
            url="https://example.com/mcp",
            headers=(("Authorization", ""),),
        ),
    )
    assert service.list_mcp_servers()["remote"]["headers"] == {
        "Authorization": "Bearer old"
    }


def test_switching_transport_discards_the_other_side_secrets(
    tmp_path: Path,
) -> None:
    """stdio env has no meaning for an http server, and must not be carried over.

    Only the keys belonging to the chosen transport are written, so a stray
    ``env`` beside a ``url`` would make create_transport's command-vs-url check
    ambiguous.
    """
    service = _service(tmp_path)
    service.add_mcp_server(McpServerConfig(name="s", command="c", env=(("A", "1"),)))
    service.update_mcp_server(
        "s", McpServerConfig(name="s", url="https://example.com/mcp")
    )
    assert service.list_mcp_servers()["s"] == {"url": "https://example.com/mcp"}


def test_update_can_rename(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.add_mcp_server(McpServerConfig(name="before", command="x"))
    service.update_mcp_server("before", McpServerConfig(name="after", command="x"))
    stored = service.list_mcp_servers()
    assert "before" not in stored and "after" in stored


def test_rename_onto_an_existing_name_is_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.add_mcp_server(McpServerConfig(name="a", command="x"))
    service.add_mcp_server(McpServerConfig(name="b", command="y"))
    with pytest.raises(ConfigValidationError, match="already exists"):
        service.update_mcp_server("a", McpServerConfig(name="b", command="x"))


def test_update_and_delete_report_a_missing_server(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ConfigValidationError, match="does not exist"):
        service.update_mcp_server("ghost", McpServerConfig(name="ghost", command="x"))
    with pytest.raises(ConfigValidationError, match="does not exist"):
        service.delete_mcp_server("ghost")


def test_delete_removes_only_the_named_server(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.add_mcp_server(McpServerConfig(name="keep", command="x"))
    service.add_mcp_server(McpServerConfig(name="drop", command="y"))
    service.delete_mcp_server("drop")
    assert set(service.list_mcp_servers()) == {"keep"}


def test_crud_leaves_other_config_untouched(tmp_path: Path) -> None:
    """The MCP block is the only thing a save edits."""
    service = _service(
        tmp_path, {"providers": {"p": {"type": "ollama"}}, "mode": "ask"}
    )
    service.add_mcp_server(McpServerConfig(name="s", command="x"))
    payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert payload["providers"] == {"p": {"type": "ollama"}}
    assert payload["mode"] == "ask"


# ── the probe, which only means anything when it really connects ─────


@pytest.mark.asyncio
async def test_probe_connects_a_real_stdio_server(mcp_server_path: str) -> None:
    """A passing probe is a real initialize + tools/list, not a shape check."""
    result = await probe_mcp_server(
        {"command": sys.executable, "args": [mcp_server_path]}
    )
    assert result.ok, result.error
    assert result.server_name == "test-server"
    assert result.tool_count == 1
    assert "echo" in result.tool_names


@pytest.mark.asyncio
async def test_probe_reports_a_missing_command_without_raising() -> None:
    """The most common stdio failure, returned as a result rather than thrown."""
    result = await probe_mcp_server({"command": "nova-no-such-binary-xyz", "args": []})
    assert result.ok is False
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_probe_reports_a_malformed_config() -> None:
    result = await probe_mcp_server({})
    assert result.ok is False
    assert result.error


@pytest.mark.asyncio
async def test_probe_reports_an_unreachable_host_without_a_traceback() -> None:
    """A remote failure is a sentence a user can act on, not a class name.

    Port 1 refuses connections on every platform this runs on, so the branch is
    reached without a network dependency.
    """
    result = await probe_mcp_server({"url": "http://127.0.0.1:1/mcp"})
    assert result.ok is False
    assert result.error
    assert "Traceback" not in result.error
    assert not result.error.startswith(("ClientConnectorError", "OSError"))
