"""Reading and restoring turn checkpoints.

A checkpoint is the set of files a turn overwrote, captured just before each
write. Restoring one puts those files back and reports what it could not: a file
someone edited after the agent did is left alone unless the caller insists, and a
binary or oversized pre-image is named rather than silently skipped.

The conversation is not touched here. Dropping the messages after a checkpoint is
a session concern and lives where the data source is (the route and the CLI), so
this module stays a pure filesystem operation that can be tested against a tmp
directory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from nova.tools.checkpoints import (
    ENTRIES_FILENAME,
    META_FILENAME,
    checkpoint_root,
)

log = logging.getLogger(__name__)


@dataclass
class CheckpointSummary:
    """One rewind point, as the client lists it."""

    session_id: str
    checkpoint_id: str
    label: str
    created_at: int
    files: int
    #: Entries whose content was not kept (binary, too large).
    skipped: int


@dataclass
class RestoreReport:
    """What a restore actually did."""

    restored: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def list_checkpoints(session_id: str) -> list[CheckpointSummary]:
    """Every checkpoint of *session_id*, newest first."""
    directory = checkpoint_root() / session_id
    try:
        children = [item for item in directory.iterdir() if item.is_dir()]
    except OSError:
        return []

    summaries: list[tuple[int, CheckpointSummary]] = []
    for child in children:
        meta = _read_meta(child)
        if meta is None:
            continue
        entries = _read_entries(child)
        try:
            # Two turns in the same millisecond are common; the directory's own
            # timestamp is the tie-breaker so "newer" stays meaningful.
            tie_break = child.stat().st_mtime_ns
        except OSError:
            tie_break = 0
        summaries.append(
            (
                tie_break,
                CheckpointSummary(
                    session_id=session_id,
                    checkpoint_id=str(meta.get("checkpoint_id") or child.name),
                    label=str(meta.get("label") or ""),
                    created_at=int(meta.get("created_at") or 0),
                    files=len(entries),
                    skipped=sum(1 for entry in entries if entry.get("skipped")),
                ),
            )
        )
    summaries.sort(key=lambda pair: (pair[1].created_at, pair[0]), reverse=True)
    return [summary for _, summary in summaries]


def restore_files(
    session_id: str,
    checkpoint_id: str,
    *,
    force: bool = False,
) -> RestoreReport:
    """Put back every file the checkpoint recorded.

    Args:
        session_id: Owning session.
        checkpoint_id: Id of the rewind point (the turn's user message id).
        force: Restore even when the file changed after the agent wrote it.

    Returns:
        The paths restored, the paths deleted (files the turn created), and the
        entries skipped with a reason.

    Raises:
        FileNotFoundError: when the checkpoint does not exist.
    """
    directory = checkpoint_root() / session_id / checkpoint_id
    meta = _read_meta(directory)
    if meta is None:
        raise FileNotFoundError(f"No checkpoint {checkpoint_id} for {session_id}")

    workspace = Path(str(meta.get("workspace") or ""))
    report = RestoreReport()

    for entry in _read_entries(directory):
        path_text = str(entry.get("path") or "")
        path = Path(path_text)
        if not path_text:
            report.skipped.append({"path": path_text, "reason": "no-path"})
            continue
        # A checkpoint is data on disk; it must not be able to write outside the
        # workspace it was taken in, however it was tampered with.
        if not workspace.is_dir() or not _is_inside(path, workspace):
            report.skipped.append({"path": path_text, "reason": "outside-workspace"})
            continue

        reason = str(entry.get("skipped") or "")
        if reason:
            report.skipped.append({"path": path_text, "reason": reason})
            continue

        if not force and not _still_matches(path, entry):
            report.skipped.append({"path": path_text, "reason": "changed-since"})
            continue

        try:
            if entry.get("existed"):
                _write_atomic(path, str(entry.get("content") or ""))
                report.restored.append(path_text)
            elif path.exists():
                path.unlink()
                _prune_empty_parents(path.parent, workspace)
                report.deleted.append(path_text)
            else:
                report.deleted.append(path_text)
        except OSError as error:
            log.exception("Restore failed for %s", path)
            report.skipped.append({"path": path_text, "reason": f"error: {error}"})

    return report


def discard_checkpoints_from(session_id: str, checkpoint_id: str) -> None:
    """Drop *checkpoint_id* and every checkpoint newer than it.

    A rewind deletes the messages from that point on, so the checkpoint itself no
    longer names a turn in the conversation. Keeping it would leave a rewind point
    whose chat can no longer be truncated.
    """
    summaries = list_checkpoints(session_id)
    index = next(
        (
            position
            for position, item in enumerate(summaries)
            if item.checkpoint_id == checkpoint_id
        ),
        None,
    )
    if index is None:
        return
    # Newest first, so the target and everything before its index go.
    for stale in summaries[: index + 1]:
        _remove(checkpoint_root() / session_id / stale.checkpoint_id)


def _read_meta(directory: Path) -> dict[str, object] | None:
    try:
        raw = (directory / META_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Ignoring malformed checkpoint meta at %s", directory)
        return None
    return payload if isinstance(payload, dict) else None


def _read_entries(directory: Path) -> list[dict[str, object]]:
    """Merge the append-only log into one entry per path, first-seen order.

    A line without `existed` is a post-hash update for a path already recorded;
    it exists so a second write in the same turn can move the hash without
    rewriting (and re-reading) the whole pre-image.
    """
    try:
        lines = (directory / ENTRIES_FILENAME).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    merged: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # A torn last line is what an interrupted checkpoint looks like; the
            # entries before it are still valid.
            log.warning("Ignoring malformed checkpoint entry at %s", directory)
            continue
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "")
        if not path:
            continue
        if "existed" not in entry:
            if path in merged:
                merged[path]["post_hash"] = entry.get("post_hash")
            continue
        if path not in merged:
            order.append(path)
        merged[path] = entry
    return [merged[path] for path in order]


def _is_inside(path: Path, workspace: Path) -> bool:
    try:
        path.resolve().relative_to(workspace.resolve())
    except (OSError, ValueError):
        return False
    return True


def _still_matches(path: Path, entry: dict[str, object]) -> bool:
    """Whether the file still holds what the agent last wrote."""
    expected = str(entry.get("post_hash") or "")
    if not expected:
        # A checkpoint written before hashes were recorded: only an entry that
        # never existed (a created file) is safe to undo blindly.
        return not entry.get("existed")
    try:
        current = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        current = ""
    return current == expected


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.nova-restore")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _prune_empty_parents(directory: Path, workspace: Path) -> None:
    current = directory
    while current != workspace and _is_inside(current, workspace):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _remove(directory: Path) -> None:
    import shutil

    shutil.rmtree(directory, ignore_errors=True)


def session_paths(session_id: str) -> set[str]:
    """Every file path any checkpoint of *session_id* recorded.

    Used to answer "what did this session touch", which is what a commit should
    contain. Paths come back absolute, the way the capture layer stored them.
    """
    directory = checkpoint_root() / session_id
    try:
        children = [item for item in directory.iterdir() if item.is_dir()]
    except OSError:
        return set()
    paths: set[str] = set()
    for child in children:
        for entry in _read_entries(child):
            path = str(entry.get("path") or "")
            if path:
                paths.add(path)
    return paths
