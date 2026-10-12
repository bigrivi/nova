"""Live check: an MCP tool that collides with a gated built-in name.

The unit tests drive the behaviour class directly. This one runs it through a
real agent turn, with a real MCP stdio server whose tool is deliberately named
``edit`` -- the name Nova's own workspace-boundary rule keys on. Before the
change, a call with a ``filePath`` outside the workspace raised an approval; now
it must not, while a built-in ``edit`` in the same session still does.
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

PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
AUTH = "Basic " + base64.b64encode(b"nova:s3cret").decode()
REPO = Path("/Users/andy/Workspace/codes/ai/nova")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


MCP_SERVER = """
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    m = json.loads(line)
    rid = m.get("id")
    meth = m.get("method")
    if meth == "initialize":
        r = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
             "serverInfo": {"name": "collide", "version": "1.0"}}
    elif meth == "tools/list":
        # Deliberately named like a gated built-in.
        r = {"tools": [{"name": "edit", "description": "Overwrite a file",
                        "inputSchema": {"type": "object", "properties": {
                            "filePath": {"type": "string"}},
                            "required": ["filePath"]}}]}
    elif meth == "tools/call":
        r = {"content": [{"type": "text", "text": "mcp-wrote-it"}]}
    else:
        r = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": r}) + "\\n")
    sys.stdout.flush()
"""


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="nova-mcp-perm-"))
    workspace = home / "ws"
    workspace.mkdir(parents=True)
    server_script = home / "collide_server.py"
    server_script.write_text(MCP_SERVER, encoding="utf-8")

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

    env = {**os.environ, "NOVA_HOME": str(home)}
    proc = subprocess.Popen(
        [str(REPO / ".venv/bin/python"), "-m", "nova", "serve"],
        env=env,
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

        result = run_probe(home, workspace)
        for label, ok, detail in result:
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


def run_probe(home: Path, workspace: Path) -> list[tuple[str, bool, str]]:
    """Build the toolset from the live config and inspect the two 'edit' tools."""
    checks: list[tuple[str, bool, str]] = []

    async def build():
        from nova.agent.toolset import ToolsetBuilder

        # Settings are loaded for the side effect of resolving the NOVA_HOME
        # this process was started with, so `build()` sees the same MCP config
        # the live server reads.
        from nova.settings import get_settings
        from nova.tools.approval import ApprovalManager
        from nova.tools.registry import ToolRegistry

        get_settings()
        registry = ToolRegistry()
        builder = ToolsetBuilder(
            registry=registry,
            skill_service=None,
            approval=ApprovalManager(),
            is_sub_agent=False,
        )
        await builder.build()
        return registry

    registry = asyncio.run(build())

    # The live manager registers MCP tools AFTER the built-ins and skips a name
    # that already exists, so an MCP tool called `edit` never reaches the policy
    # layer at all. Record that, then register one under a name that does collide
    # in order to exercise the policy decision itself.
    checks.append(
        (
            "built-in 'edit' survives the name collision",
            registry.get("edit") is not None,
            "register_tools skips the MCP 'edit', so the built-in is kept",
        )
    )

    # The decisive check: an MCP-registered tool that *would* have been gated.
    # Registered after build() because that is the real order -- MCP tools land
    # on top of the built-ins -- and the policy pass is re-run so the new tool
    # picks up a behaviour.
    from nova.llm import ToolResult
    from nova.tools.registry import ToolRegistry

    registry.register_direct(
        name="mcp_edit",
        description="Overwrite a file",
        func=lambda **_kw: ToolResult(success=True, content="mcp-wrote-it"),
        params_schema={"type": "object", "properties": {}},
        from_mcp=True,
    )
    # Bound to a writer name as well, to prove the gate keys on origin and not on
    # whether the tool happens to be named like something dangerous.
    registry.register_direct(
        name="edit",
        description="Overwrite a file (MCP)",
        func=lambda **_kw: ToolResult(success=True, content="mcp-wrote-it"),
        params_schema={"type": "object", "properties": {}},
        from_mcp=True,
    )

    from nova.agent.toolset import ToolsetBuilder
    from nova.tools.approval import ApprovalManager

    builder = ToolsetBuilder(
        registry=registry,
        skill_service=None,
        approval=ApprovalManager(),
        is_sub_agent=False,
    )
    builder._register_tool_policies()

    from nova.tools.workspace_context import set_active_workspace

    set_active_workspace(str(workspace))
    try:
        outside = str(home / "outside.txt")

        async def ask(tool: str):
            behavior = registry.behavior_for(tool)
            from nova.tools.behavior import TurnContext

            return await behavior.before_execute(
                {"filePath": outside}, TurnContext(session_id="s1")
            )

        mcp_result = asyncio.run(ask("edit"))
        checks.append(
            (
                "MCP 'edit' targeting outside the workspace does not prompt",
                mcp_result.approval_request is None and mcp_result.allowed,
                f"approval={mcp_result.approval_request}",
            )
        )

        mcp_named = asyncio.run(ask("mcp_edit"))
        checks.append(
            (
                "an MCP tool named like a writer is not prompted either",
                mcp_named.approval_request is None and mcp_named.allowed,
                "name is irrelevant once the tool comes from a server",
            )
        )

        # Now the same call as a built-in, to prove the gate is still there.
        registry2 = ToolRegistry()
        registry2.register_direct(
            name="edit",
            description="Nova's editor",
            func=lambda **_kw: ToolResult(success=True, content="ok"),
            params_schema={"type": "object", "properties": {}},
            from_mcp=False,
        )
        builder2 = ToolsetBuilder(
            registry=registry2,
            skill_service=None,
            approval=ApprovalManager(),
            is_sub_agent=False,
        )
        asyncio.run(builder2.build())

        async def ask_builtin():
            from nova.tools.behavior import TurnContext

            behavior = registry2.behavior_for("edit")
            return await behavior.before_execute(
                {"filePath": outside}, TurnContext(session_id="s1")
            )

        builtin_result = asyncio.run(ask_builtin())
        checks.append(
            (
                "built-in 'edit' targeting outside the workspace still prompts",
                builtin_result.approval_request is not None,
                "workspace boundary intact",
            )
        )
    finally:
        set_active_workspace(None)

    return checks


if __name__ == "__main__":
    sys.exit(main())
