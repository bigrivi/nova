"""Pre-images of the files an agent turn touches, so the turn can be undone.

A checkpoint is written as the turn runs, not at the end: the manifest holds one
JSON line per path the first time that path is overwritten, and the line is
appended and flushed before the write reaches the disk. A turn that crashes or is
interrupted therefore still has a usable checkpoint, which is exactly when a
rewind matters.

Only ``write`` and ``edit`` report here. Shell commands, ``code_run`` and MCP
tools can change anything, so a rewind cannot promise to undo them: the report
names them instead of pretending.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

#: Largest text pre-image kept. Bigger files are recorded as skipped with the
#: original size, so the rewind report can say what it could not restore.
MAX_SNAPSHOT_BYTES = 256 * 1024

#: Checkpoints kept per session; the oldest are dropped first.
MAX_CHECKPOINTS_PER_SESSION = 50

META_FILENAME = "meta.json"
ENTRIES_FILENAME = "entries.jsonl"


def checkpoint_root() -> Path:
    """Directory holding every session's checkpoints."""
    from nova.tools.permissions import nova_home

    return nova_home() / "checkpoints"


@dataclass
class TurnRecorder:
    """One turn's worth of pre-images. The same object is shared by every tool
    call the turn makes."""

    session_id: str
    checkpoint_id: str
    label: str
    workspace: str
    recorded: set[str] = field(default_factory=set)

    @property
    def directory(self) -> Path:
        return checkpoint_root() / self.session_id / self.checkpoint_id

    def already_recorded(self, path: Path) -> bool:
        return str(path) in self.recorded


_recorder: ContextVar[TurnRecorder | None] = ContextVar(
    "nova_turn_recorder", default=None
)


def begin_turn(
    session_id: str,
    checkpoint_id: str,
    label: str,
    workspace: str | None,
) -> TurnRecorder | None:
    """Mark the turn a tool call belongs to. Returns None when it cannot be
    recorded (no session or no checkpoint id), which turns capture into a no-op
    rather than an error the tool would have to handle."""
    if not session_id or not checkpoint_id:
        return None
    recorder = TurnRecorder(
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        label=label.strip()[:200],
        workspace=workspace or "",
    )
    _recorder.set(recorder)
    return recorder


def current_recorder() -> TurnRecorder | None:
    """The recorder for the turn running in this task, if any."""
    return _recorder.get()


def record_write(path: Path, old_text: str | None, new_text: str) -> None:
    """Store the pre-image of *path* before *new_text* is written to it.

    The post-image hash is stored with it: a restore compares that hash against
    what is on disk and refuses to overwrite a file someone changed after the
    agent did. Duplicate calls for one path in a turn are ignored -- the first
    pre-image is the one a rewind has to restore. Oversized and binary content is
    recorded as skipped rather than silently dropped.
    """
    recorder = _recorder.get()
    if recorder is None:
        return
    if recorder.already_recorded(path):
        # The same file written twice in one turn: the pre-image stays the first
        # one, but the post-image has to move to the latest write, or a restore
        # would report the agent's own second write as someone else's edit.
        _append_entry(
            recorder,
            {
                "path": str(path),
                "post_hash": hashlib.sha256(new_text.encode("utf-8")).hexdigest(),
            },
        )
        return
    recorder.recorded.add(str(path))

    entry: dict[str, object] = {
        "path": str(path),
        "existed": old_text is not None,
        "post_hash": hashlib.sha256(new_text.encode("utf-8")).hexdigest(),
    }
    if old_text is None:
        entry["content"] = None
    elif "\x00" in old_text:
        entry["skipped"] = "binary"
    elif len(old_text.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        entry["skipped"] = "too-large"
    else:
        entry["content"] = old_text

    try:
        _append_entry(recorder, entry)
    except OSError:
        # A checkpoint that cannot be written must not fail the edit the user
        # asked for; the turn still happens, the rewind just will not offer it.
        log.exception("Checkpoint write failed for %s", path)


def _append_entry(recorder: TurnRecorder, entry: dict[str, object]) -> None:
    directory = recorder.directory
    directory.mkdir(parents=True, exist_ok=True)
    meta = directory / META_FILENAME
    if not meta.exists():
        meta.write_text(
            json.dumps(
                {
                    "session_id": recorder.session_id,
                    "checkpoint_id": recorder.checkpoint_id,
                    "label": recorder.label,
                    "workspace": recorder.workspace,
                    "created_at": int(time.time() * 1000),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        # A new rewind point is the only moment the set can outgrow its cap.
        prune_session(recorder.session_id)
    with (directory / ENTRIES_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def prune_session(session_id: str) -> None:
    """Keep only the newest checkpoints for *session_id*."""
    directory = checkpoint_root() / session_id
    try:
        children = sorted(
            (item for item in directory.iterdir() if item.is_dir()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in children[MAX_CHECKPOINTS_PER_SESSION:]:
        _remove_tree(stale)


def remove_session(session_id: str) -> None:
    """Drop every checkpoint of a deleted session."""
    _remove_tree(checkpoint_root() / session_id)


def _remove_tree(directory: Path) -> None:
    import shutil

    try:
        shutil.rmtree(directory, ignore_errors=True)
    except OSError:
        log.exception("Could not remove checkpoint directory %s", directory)
