"""Approvals the user chose to keep, scoped to one workspace.

The policy in ``permissions.json`` is hand-written by the user. A remembered
approval is generated state, so it lives in its own file per workspace rather
than in that policy:

* a mis-clicked "always" cannot leak into another repository;
* deleting the file revokes everything it held, with no other edit;
* ``permissions.json`` stays exactly what the user wrote.

A file is keyed by the workspace path, so two checkouts of the same project do
not share grants — the path *is* the scope, and that is the whole point.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Bound on one workspace's grants. A file that grows without limit is one a
#: user never reviews; dropping the oldest keeps it readable.
MAX_GRANTS = 100

FILENAME_SUFFIX = ".json"


def grants_dir() -> Path:
    from nova.tools.permissions import nova_home

    return nova_home() / "grants"


def grants_path(workspace: str) -> Path:
    """Where one workspace's grants live.

    Args:
        workspace: Absolute workspace path.

    Returns:
        A path whose name is the hash of the *resolved* directory, so a symlink
        and its target share grants and two look-alike paths cannot collide.
    """
    try:
        resolved = str(Path(workspace).expanduser().resolve())
    except OSError:
        resolved = workspace
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    return grants_dir() / f"{digest}{FILENAME_SUFFIX}"


def load(workspace: str) -> set[tuple[str, str, str]]:
    """The ``(rule, family, digest)`` triples saved for *workspace*.

    A missing or malformed file yields an empty set: grants are convenience, and
    a broken one must not refuse the command outright or fail the tool call.
    """
    payload = _read(workspace)
    return {
        (
            str(entry["rule"]),
            str(entry.get("family") or ""),
            str(entry.get("digest") or ""),
        )
        for entry in payload.get("grants", [])
        if entry.get("rule")
    }


def entries(workspace: str) -> list[dict[str, Any]]:
    """The saved grants as the UI lists them, newest first.

    Two grants made in the same millisecond share a timestamp, so the sort is the
    stable one plus a reversal: file order is insertion order, which makes the
    later write win the tie.
    """
    payload = _read(workspace)
    saved = [entry for entry in payload.get("grants", []) if entry.get("rule")]
    return list(reversed(sorted(saved, key=lambda entry: entry.get("created_at", 0))))


def add(workspace: str, rule: str, family: str = "", digest: str = "") -> None:
    """Persist one grant for *workspace*, replacing an identical triple.

    Args:
        workspace: Absolute workspace path.
        rule: Rule description, which is the grant's identity.
        family: Narrowing to the command the user actually saw.
        digest: Further narrowing to an inline script, when there was one.
    """
    if not rule or not workspace:
        return
    payload = _read(workspace)
    existing = [
        entry
        for entry in payload.get("grants", [])
        if not (
            entry.get("rule") == rule
            and (entry.get("family") or "") == family
            and (entry.get("digest") or "") == digest
        )
    ]
    existing.append(
        {
            "rule": rule,
            "family": family,
            "digest": digest,
            "created_at": int(time.time() * 1000),
        }
    )
    payload["grants"] = existing[-MAX_GRANTS:]
    _write(workspace, payload)


def clear(workspace: str) -> None:
    """Forget every saved grant for *workspace*."""
    try:
        grants_path(workspace).unlink()
    except OSError:
        return


def _read(workspace: str) -> dict[str, Any]:
    path = grants_path(workspace)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {"workspace": workspace, "grants": []}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Ignoring malformed grants file at %s", path)
        return {"workspace": workspace, "grants": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("grants"), list):
        return {"workspace": workspace, "grants": []}
    return payload


def _write(workspace: str, payload: dict[str, Any]) -> None:
    path = grants_path(workspace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"workspace": workspace, "grants": payload.get("grants", [])},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        # Same posture as permissions.json: anyone who can edit this file can
        # authorise a command, so it is not world readable.
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError:
        # Losing a grant costs one repeat prompt; failing here would fail the
        # tool call the user already approved.
        log.exception("Could not save grant for %s", workspace)
