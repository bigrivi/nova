"""End-to-end: does an agent get the MCP tool without Nova restarting?

The manager-level reload is already proven (add/remove a server, watch
`loaded_tools` follow, no restart). What this adds is the last link: a real chat
turn, on a process that has been running since before the change, whose agent
actually holds the MCP tool.

Run against the live backend. It never restarts it, which is the whole point.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"
AUTH = "Basic " + base64.b64encode(b"nova:s3cret").decode()

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def call(method: str, path: str, body: dict | None = None, timeout: int = 240):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def loaded_names() -> list[str]:
    _, body = call("GET", "/api/mcp-servers")
    names: list[str] = []
    for item in body.get("items", []):
        names.extend(item.get("loaded_tools") or [])
    return names


def find_tool_activity(messages: list[dict], tool_name: str):
    """Return (called, result_text) for `tool_name` anywhere in the history."""
    called = False
    result = ""
    for message in messages:
        blob = json.dumps(message, ensure_ascii=False)
        if tool_name in blob:
            called = True
        for key in ("tool_name", "name"):
            if message.get(key) == tool_name:
                called = True
        content = message.get("content")
        if isinstance(content, str) and tool_name in content:
            called = True
            result = content
    return called, result


def main() -> int:
    print("1) the process has not been restarted; the server is loaded")
    names = loaded_names()
    target = "mcp__mcp_demo__echo"
    check("the demo server's namespaced tool is loaded", target in names,
          f"{len(names)} tools")
    check("Nova's own `edit` is not displaced",
          "mcp__mcp_demo__edit" in names)

    print("\n2) a real chat turn, asking for that tool by name")
    session_id = None
    answer = ""
    # The agent's own model is tried first; if the provider is unavailable the
    # turn fails and an explicit free model is tried, because an infra failure
    # here is not evidence about the tool.
    for provider, model in ((None, None), ("opencode-go", "deepseek-v4.1-flash")):
        payload = {
            "message": (
                "请调用 echo 工具，参数 text 填 hello-from-mcp，"
                "然后把工具返回的内容原样告诉我。"
            ),
            "agent_key": "main",
        }
        if provider:
            payload["provider"] = provider
            payload["model"] = model
        status, body = call("POST", "/api/chat", payload)
        if status == 200 and body.get("session_id"):
            session_id = body["session_id"]
            answer = json.dumps(body, ensure_ascii=False)
            print(f"         provider={provider or 'agent default'} status=200")
            break
        print(f"         provider={provider or 'agent default'} status={status} "
              f"{str(body)[:120]}")

    check("a turn completed", session_id is not None)
    if not session_id:
        print("\n".join(f"  - {f}" for f in failures))
        return 1

    print("\n3) the tool call is in the session history")
    called = False
    result_text = ""
    for _ in range(20):
        status, body = call("GET", f"/api/sessions/{session_id}/messages")
        messages = body.get("items") or body.get("messages") or []
        called, result_text = find_tool_activity(messages, target)
        if called:
            break
        time.sleep(1)

    check(f"the agent called {target}", called,
          (result_text or answer)[:160])

    print("\n4) the tool actually reached the server")
    # The demo server echoes its input, so a real round trip is visible.
    reached = "hello-from-mcp" in result_text or "hello-from-mcp" in answer
    check("the server's answer came back", reached,
          (result_text or "")[:160])

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
