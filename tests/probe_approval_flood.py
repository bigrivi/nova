"""Feedback loop: how many distinct shell commands does one turn need approved?

The complaint is that a WeChat turn asks for approval over and over on commands
that are not actually dangerous. This replays the shell commands from a real
session through the classifier that decides, so the answer is a count and a list
rather than an impression.

    NOVA_DB=~/.nova/nova.db \
    NOVA_SESSION=ac26bd9e-7dd1-4b65-83bd-584b9cfa073e \
    .venv/bin/python tests/probe_approval_flood.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

DB = Path(os.environ.get("NOVA_DB", Path.home() / ".nova/nova.db"))
SESSION = os.environ.get("NOVA_SESSION", "")


def session_shell_commands(session_id: str) -> list[str]:
    """Every shell command the session actually ran, in order."""
    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            "SELECT tool_calls FROM messages "
            "WHERE session_id = ? AND tool_calls IS NOT NULL ORDER BY rowid",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    commands: list[str] = []
    for (raw,) in rows:
        try:
            calls = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict) or call.get("name") != "shell":
                continue
            args = call.get("arguments") or call.get("input") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                continue
            command = args.get("command")
            if isinstance(command, str) and command.strip():
                commands.append(command.strip())
    return commands


async def main() -> None:
    if not SESSION:
        raise SystemExit("set NOVA_SESSION to a session id")

    commands = session_shell_commands(SESSION)
    if not commands:
        print("no shell commands found in that session")
        return

    print(f"session {SESSION[:8]}")
    print("（含变量 = 允许白名单按整条命令匹配，这类命令永远命中不了）")
    print(f"shell 调用总数 : {len(commands)}")
    print(f"去重后        : {len(set(commands))}")
    print()

    # Classify each distinct command the way a turn does.
    from nova.tools.shell import is_dangerous

    counts: Counter[str] = Counter(commands)
    flagged: list[tuple[int, str]] = []
    for command, times in counts.most_common():
        if is_dangerous(command)[0]:
            flagged.append((times, command))

    print(f"需要审批的去重命令 : {len(flagged)} / {len(counts)}")
    print(f"这些命令累计出现   : {sum(t for t, _ in flagged)} / {len(commands)}")
    print()
    for times, command in flagged:
        first = command.splitlines()[0][:110]
        print(f"  x{times:<3} {first}")

    # The allow-list is keyed on the whole command string, so a command that
    # embeds a varying value can never hit it twice.
    print()
    print("允许白名单是按整条命令字符串记的，以下命令若带变量就永远命中不了：")
    variable = [c for c in counts if any(ch in c for ch in "$`'\"")]
    for command in variable[:5]:
        print(f"  {command.splitlines()[0][:110]}")
    print(f"  （共 {len(variable)} 条含变量）")


if __name__ == "__main__":
    asyncio.run(main())
