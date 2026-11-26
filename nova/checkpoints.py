"""Nova-facing checkpoint queries and restore operations."""

from __future__ import annotations

from novakit.checkpoints import CheckpointStore, CheckpointSummary, RestoreReport

from nova.tools.checkpoints import checkpoint_root

_store = CheckpointStore(checkpoint_root)


def list_checkpoints(session_id: str) -> list[CheckpointSummary]:
    """List Nova checkpoints for a session, newest first.

    Args:
        session_id: Session whose checkpoints should be listed.

    Returns:
        Checkpoint summaries in descending creation order.
    """
    return _store.list_checkpoints(session_id)


def restore_files(
    session_id: str,
    checkpoint_id: str,
    *,
    force: bool = False,
) -> RestoreReport:
    """Restore files captured by a Nova checkpoint.

    Args:
        session_id: Owning session identifier.
        checkpoint_id: Rewind point to restore.
        force: Restore even when a file changed after the agent wrote it.

    Returns:
        A report of restored, deleted, and skipped paths.

    Raises:
        FileNotFoundError: When the checkpoint does not exist.
    """
    return _store.restore_files(session_id, checkpoint_id, force=force)


def discard_checkpoints_from(session_id: str, checkpoint_id: str) -> None:
    """Discard a Nova checkpoint and every newer checkpoint.

    Args:
        session_id: Owning session identifier.
        checkpoint_id: Oldest rewind point to discard.
    """
    _store.discard_checkpoints_from(session_id, checkpoint_id)


def session_paths(session_id: str) -> set[str]:
    """Return every file path recorded by a Nova session's checkpoints.

    Args:
        session_id: Session whose touched paths should be returned.

    Returns:
        Absolute path strings captured by the session.
    """
    return _store.session_paths(session_id)


__all__ = [
    "CheckpointSummary",
    "RestoreReport",
    "discard_checkpoints_from",
    "list_checkpoints",
    "restore_files",
    "session_paths",
]
