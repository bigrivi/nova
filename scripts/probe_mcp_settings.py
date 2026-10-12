"""Live end-to-end check of the MCP settings endpoints.

Runs a real Nova backend on a throwaway NOVA_HOME (so the developer's real
config.json is never touched) and drives the endpoints the settings UI calls:
list, add, test, update, delete -- with a real MCP stdio server on the far end
of the connection test, and a command that does not exist on the other.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
AUTH = "Basic " + base64.b64encode(b"nova:s3cret").decode()
REPO = Path(__file__).resolve().parents[1]

failures: list[str] = []


def check(label: str, got: object, want: object) -> None:
    ok = got == want
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}: {got!r}")
    if not ok:
        failures.append(f"{label}: got {got!r}, want {want!r}")


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": AUTH,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def write_fake_mcp_server(directory: Path) -> Path:
    """A real MCP stdio server: speaks initialize / tools/list over stdin."""
    script = directory / "fake_mcp_server.py"
    script.write_text(
        textwrap.dedent(
            """\
            import json, sys
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                rid = msg.get("id")
                method = msg.get("method")
                if method == "initialize":
                    result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "live-probe-server", "version": "2.1.0"}}
                elif method == "tools/list":
                    result = {"tools": [{"name": "search", "description": "Search things",
                                         "inputSchema": {"type": "object", "properties": {}}},
                                        {"name": "fetch", "description": "Fetch a thing",
                                         "inputSchema": {"type": "object", "properties": {}}}]}
                elif method == "tools/call":
                    result = {"content": [{"type": "text", "text": "done"}]}
                else:
                    result = {}
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\\n")
                sys.stdout.flush()
            """
        ),
        encoding="utf-8",
    )
    return script


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="nova-mcp-live-"))
    workspace = home / "work"
    workspace.mkdir(parents=True)
    server_script = write_fake_mcp_server(workspace)

    (home / "config.json").write_text(
        json.dumps(
            {
                "server": {"host": "127.0.0.1", "port": PORT, "log_level": "WARNING"},
                "providers": {},
                "mcp_servers": {},
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
                with urllib.request.urlopen(f"{BASE}/health", timeout=2) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.5)
        else:
            print("backend never came up")
            return 1

        print("\n-- list, empty")
        status, body = call("GET", "/api/mcp-servers")
        check("status", status, 200)
        check("items", body.get("items"), [])

        print("\n-- add a real stdio server")
        status, body = call(
            "POST",
            "/api/config/mcp/add",
            {
                "name": "  probe  ",
                "command": sys.executable,
                "args": [str(server_script)],
                "env": [{"key": "PROBE_TOKEN", "value": "s3cret-value"}],
                "url": "",
                "headers": [],
            },
        )
        check("status", status, 200)
        items = body.get("items", [])
        check("count", len(items), 1)
        record = items[0] if items else {}
        check("name trimmed", record.get("name"), "probe")
        check("transport", record.get("transport"), "stdio")
        check("command", record.get("command"), sys.executable)
        # The value must never come back; only the name of the key.
        check("env_keys", record.get("env_keys"), ["PROBE_TOKEN"])
        check(
            "value withheld",
            "s3cret-value" in json.dumps(body),
            False,
        )

        print("\n-- test connection against that real server")
        status, body = call(
            "POST",
            "/api/config/mcp/test",
            {
                "name": "probe",
                "command": sys.executable,
                "args": [str(server_script)],
                "env": [{"key": "PROBE_TOKEN", "value": "s3cret-value"}],
                "url": "",
                "headers": [],
            },
        )
        check("status", status, 200)
        check("ok", body.get("ok"), True)
        check("server_name", body.get("server_name"), "live-probe-server")
        check("server_version", body.get("server_version"), "2.1.0")
        check("tool_count", body.get("tool_count"), 2)
        check("tool_names", sorted(body.get("tool_names", [])), ["fetch", "search"])

        print("\n-- test a command that does not exist")
        status, body = call(
            "POST",
            "/api/config/mcp/test",
            {
                "name": "ghost",
                "command": "definitely-not-a-real-binary-xyz",
                "args": [],
                "env": [],
                "url": "",
                "headers": [],
            },
        )
        check("status", status, 200)
        check("ok", body.get("ok"), False)
        print(f"         error: {body.get('error')}")
        check("names the command", "definitely-not-a-real-binary-xyz" in body.get("error", ""), True)

        print("\n-- test an unreachable remote URL")
        status, body = call(
            "POST",
            "/api/config/mcp/test",
            {
                "name": "remote",
                "command": "",
                "args": [],
                "env": [],
                "url": "http://127.0.0.1:1/mcp",
                "headers": [],
            },
        )
        check("ok", body.get("ok"), False)
        print(f"         error: {body.get('error')[:90]}")

        print("\n-- a test writes nothing")
        stored = json.loads((home / "config.json").read_text(encoding="utf-8"))
        check("still one server", len(stored.get("mcp_servers", {})), 1)

        print("\n-- update: change the command, keep the hidden secret")
        status, body = call(
            "POST",
            "/api/config/mcp/update",
            {
                "original_name": "probe",
                "name": "probe2",
                "command": sys.executable,
                "args": [str(server_script), "--flag"],
                "env": [{"key": "PROBE_TOKEN", "value": ""}],
                "url": "",
                "headers": [],
            },
        )
        check("status", status, 200)
        stored = json.loads((home / "config.json").read_text(encoding="utf-8"))
        servers = stored.get("mcp_servers", {})
        check("renamed", sorted(servers.keys()), ["probe2"])
        check(
            "secret survived",
            servers.get("probe2", {}).get("env", {}).get("PROBE_TOKEN"),
            "s3cret-value",
        )
        check("args updated", servers["probe2"].get("args"), [str(server_script), "--flag"])

        print("\n-- add a duplicate is refused")
        status, body = call(
            "POST",
            "/api/config/mcp/add",
            {"name": "probe2", "command": "x", "args": [], "env": [], "url": "", "headers": []},
        )
        check("status", status, 400)
        print(f"         detail: {body.get('detail')}")

        print("\n-- a config with neither command nor url is refused")
        status, body = call(
            "POST",
            "/api/config/mcp/add",
            {"name": "broken", "command": "", "args": [], "env": [], "url": "", "headers": []},
        )
        check("status", status, 400)
        print(f"         detail: {body.get('detail')}")

        print("\n-- delete")
        status, body = call("POST", "/api/config/mcp/delete", {"name": "probe2"})
        check("status", status, 200)
        check("items", body.get("items"), [])

        print("\n-- delete something absent")
        status, body = call("POST", "/api/config/mcp/delete", {"name": "probe2"})
        check("status", status, 404)

        print("\n-- the config file itself")
        stored = json.loads((home / "config.json").read_text(encoding="utf-8"))
        check("mcp_servers emptied", stored.get("mcp_servers"), {})
        check("providers untouched", stored.get("providers"), {})
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("All live checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
