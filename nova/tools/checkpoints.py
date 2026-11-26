"""Nova-owned checkpoint root over novakit's portable checkpoint engine."""

from __future__ import annotations

from pathlib import Path

from novakit.checkpoints import (
    ENTRIES_FILENAME,
    MAX_CHECKPOINTS_PER_SESSION,
    MAX_SNAPSHOT_BYTES,
    META_FILENAME,
    CheckpointStore,
    TurnRecorder,
)


def checkpoint_root() -> Path:
    """Return Nova's user-owned checkpoint directory."""
    from nova.tools.permissions import nova_home

    return nova_home() / "checkpoints"


_store = CheckpointStore(checkpoint_root)


def begin_turn(
    session_id: str,
    checkpoint_id: str,
    label: str,
    workspace: str | None,
) -> TurnRecorder | None:
    """Start checkpoint capture under Nova's configured home.

    Args:
        session_id: Owning session identifier.
        checkpoint_id: User message identifier used as the rewind point.
        label: Human-readable turn label.
        workspace: Workspace boundary used during restore.

    Returns:
        The active recorder, or None when identifiers are missing.
    """
    return _store.begin_turn(session_id, checkpoint_id, label, workspace)


def current_recorder() -> TurnRecorder | None:
    """Return the checkpoint recorder for the current Nova task."""
    return _store.current_recorder()


def record_write(path: Path, old_text: str | None, new_text: str) -> None:
    """Record a pre-image before a Nova tool writes a file.

    Args:
        path: File the tool is about to write.
        old_text: Previous text, or None when the file did not exist.
        new_text: New text used for the post-image hash.
    """
    _store.record_write(path, old_text, new_text)


def prune_session(session_id: str) -> None:
    """Prune old checkpoints for a Nova session.

    Args:
        session_id: Session whose old checkpoints should be removed.
    """
    _store.prune_session(session_id)


def remove_session(session_id: str) -> None:
    """Remove every checkpoint owned by a Nova session.

    Args:
        session_id: Session whose checkpoint directory should be removed.
    """
    _store.remove_session(session_id)


__all__ = [
    "ENTRIES_FILENAME",
    "MAX_CHECKPOINTS_PER_SESSION",
    "MAX_SNAPSHOT_BYTES",
    "META_FILENAME",
    "begin_turn",
    "checkpoint_root",
    "current_recorder",
    "prune_session",
    "record_write",
    "remove_session",
]
