"""The permission policy currently in force, read-only.

Read-only on purpose: remembered grants are still scoped to a session and held
in memory, so there is nothing here a client could write that would survive the
process. What a client *can* do is show the user which mode and which rules are
answering a command, instead of sending them to `~/.nova/permissions.json`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from nova.server.schemas import (
    PermissionPolicy,
    PermissionRuleRecord,
    ToolEffectRecord,
)
from nova.tools.permissions import (
    load_permission_mode,
    load_permissions,
    permissions_path,
)

router = APIRouter()


@router.get("/api/permissions", response_model=PermissionPolicy)
async def get_permissions() -> PermissionPolicy:
    """Return the mode and rules a tool call would be judged by."""
    path = permissions_path()
    payload = load_permissions(path)
    shell = payload.get("shell")
    shell_block = shell if isinstance(shell, dict) else {}

    return PermissionPolicy(
        mode=load_permission_mode(path),
        path=str(path),
        configured=path.is_file(),
        block_reads_outside_workspace=bool(
            payload.get("block_reads_outside_workspace", False)
        ),
        shell_allow=[str(item) for item in shell_block.get("allow") or []],
        shell_ask=[
            PermissionRuleRecord(
                description=str(entry.get("description", "")),
                match=str(entry.get("match", "")),
            )
            for entry in shell_block.get("ask") or []
            if isinstance(entry, dict)
        ],
        shell_disable=[str(item) for item in shell_block.get("disable") or []],
        tools=_tool_effects(payload.get("tools")),
    )


def _tool_effects(value: Any) -> list[ToolEffectRecord]:
    """Render the `tools` map, skipping the `_readme` key and unknown effects."""
    if not isinstance(value, dict):
        return []
    allowed = {"allow", "ask", "deny"}
    return [
        ToolEffectRecord(name=str(name), effect=str(effect))
        for name, effect in value.items()
        if not str(name).startswith("_") and str(effect) in allowed
    ]
