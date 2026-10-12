"""Live check: a server whose tool is named like a built-in is now usable.

The defect this replaces was silent: a server advertising ``edit`` was skipped for
colliding with Nova's editor, so the connection test reported a usable server and
the agent could never call it. Registering it under ``mcp__<server>__<tool>``
fixes the collision, and the part that is easy to get wrong is the call: the
namespace exists for the model, so the wrapper must still ask the server for the
name the *server* knows. A wrapper that passed the namespaced name would register
fine and fail on every invocation, which no unit test in this repo would catch
without a real server on the other end.

So this runs a real MCP stdio server, registers it into a real toolset, invokes the
namespaced wrapper, and checks that the tool the server advertised arrived.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PORT = 8796
BASE = f"http://127.0.0.1:{PORT}"
AUTH = "Basic " + base64.b64encode(b"nova:s3cret").decode()
REPO = Path("/Users/andy/Workspace/codes/ai/nova")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def add_check(
    checks: list[tuple[str, bool, str]],
    label: str,
    ok: bool,
    detail: str = "",
) -> None:
    """Append a check, tolerating the two-element shorthand."""
    checks.append((label, ok, detail))


# Echoes back the tool name it was called with, so the probe can prove the
# wrapper asked for the server's own name rather than the namespaced one.
SERVER = """
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    m = json.loads(line)
    rid, meth, params = m.get("id"), m.get("method"), m.get("params", {})
    if meth == "initialize":
        r = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
             "serverInfo": {"name": "collide", "version": "1.0"}}
    elif meth == "tools/list":
        r = {"tools": [
            {"name": "edit", "description": "Overwrite a file",
             "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
            {"name": "read", "description": "Read a file",
             "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
            {"name": "edit", "description": "Duplicate listing",
             "inputSchema": {"type": "object", "properties": {}}},
        ]}
    elif meth == "tools/call":
        r = {"content": [{"type": "text",
                          "text": "server received name=" + str(params.get("name"))}]}
    else:
        r = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": r}) + "\\n")
    sys.stdout.flush()
"""


def run_registry_checks(workspace: Path) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    from nova.llm import ToolResult
    from nova.mcp.manager import MCPManager
    from nova.tools.registry import ToolRegistry

    registry = ToolRegistry()
    for built_in in ("edit", "read", "write"):
        registry.register_direct(
            name=built_in,
            description=f"Nova's {built_in}",
            func=lambda **_kw: ToolResult(success=True, content="builtin"),
            params_schema={"type": "object", "properties": {}},
        )

    holder: dict[str, object] = {}

    async def go():
        manager = MCPManager()
        await manager.ensure_initialized()
        manager.register_tools(registry)
        # Called inside this loop on purpose: a stdio transport's subprocess
        # pipes are bound to the loop that opened them, so awaiting the wrapper
        # from a second `asyncio.run` fails against a closed loop.
        holder["result"] = await registry.get("mcp__collide__edit").func(text="hi")
        return manager

    manager = asyncio.run(go())

    names = sorted(t.name for t in registry.list_tools())
    checks.append(
        (
            "a server tool named 'edit' no longer displaces the built-in",
            registry.get("edit").description == "Nova's edit",
            f"registry: {names}",
        )
    )
    checks.append(
        (
            "it is registered under the namespaced name instead",
            "mcp__collide__edit" in registry.tools,
            "mcp__collide__edit",
        )
    )
    add_check(
        checks,
        "and is flagged as coming from a server",
        registry.get("mcp__collide__edit").from_mcp is True,
    )

    report = {entry.server: entry for entry in manager.load_report()}
    entry = report.get("collide")
    add_check(checks, "the server appears in the load report", entry is not None)
    if entry:
        checks.append(
            (
                "advertised vs loaded is reported, not hidden",
                entry.advertised == 3 and entry.loaded == 2,
                f"advertised={entry.advertised} loaded={entry.loaded}",
            )
        )
        checks.append(
            (
                "the duplicate is named as the reason",
                len(entry.skipped) == 1 and entry.skipped[0]["tool"] == "edit",
                str(entry.skipped),
            )
        )

    # The decisive one: the wrapper must reach the server with the server's own
    # tool name, not the one the model sees.
    result = holder["result"]
    checks.append(
        (
            "the namespaced tool actually calls through to the server",
            result.success and "name=edit" in result.content,
            result.content[:70],
        )
    )
    return checks


def run_api_checks() -> list[tuple[str, bool, str]]:
    req = urllib.request.Request(
        BASE + "/api/mcp-servers", headers={"Authorization": AUTH}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        items = json.loads(resp.read())["items"]
    collide = next((i for i in items if i["name"] == "collide"), None)
    checks: list[tuple[str, bool, str]] = []
    add_check(checks, "the API lists the server", collide is not None)
    if collide:
        loaded = collide.get("loaded_tools")
        skipped = collide.get("skipped_tools")
        checks.append(
            (
                "the API reports the namespaced names",
                loaded is not None and "mcp__collide__edit" in loaded,
                str(loaded),
            )
        )
        checks.append(
            (
                "the API reports the skipped tool with its reason",
                skipped is not None
                and len(skipped) == 1
                and bool(skipped[0]["reason"]),
                str(skipped),
            )
        )
    return checks


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="nova-mcp-ns-"))
    workspace = home / "ws"
    workspace.mkdir(parents=True)
    server_script = home / "collide_server.py"
    server_script.write_text(SERVER, encoding="utf-8")
    (home / "config.json").write_text(
        json.dumps(
            {
                "server": {"host": "127.0.0.1", "port": PORT, "log_level": "WARNING"},
                "providers": {},
                "mcp_servers": {
                    "collide": {
                        "command": sys.executable,
                        "args": [str(server_script)],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # The registry checks run in *this* process, so the throwaway home has to be
    # set here too -- not only on the backend subprocess. Done before any
    # settings are read, since the loader is cached.
    os.environ["NOVA_HOME"] = str(home)
    from nova.settings import get_settings

    get_settings.cache_clear()

    proc = subprocess.Popen(
        [str(REPO / ".venv/bin/python"), "-m", "nova", "serve"],
        env={**os.environ, "NOVA_HOME": str(home)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{BASE}/health", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("backend never came up")
            return 1

        for label, ok, detail in run_registry_checks(workspace):
            check(label, ok, detail)
        for label, ok, detail in run_api_checks():
            check(label, ok, detail)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if failures:
        print(f"FAILED ({len(failures)}): {failures}")
        return 1
    print("All live checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
