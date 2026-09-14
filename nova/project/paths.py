from __future__ import annotations

from pathlib import Path


def normalize_project_path(path: str | None) -> str | None:
    """Canonical form of a project path.

    Falls back to the trimmed input when the path cannot be resolved, so a
    project pointing at a deleted or unreadable directory still round-trips
    instead of being dropped.
    """
    if path is None:
        return None
    trimmed = path.strip()
    if not trimmed:
        return None
    try:
        return str(Path(trimmed).expanduser().resolve())
    except (OSError, RuntimeError):
        return trimmed


def project_label_from_path(path: str | None) -> str:
    if not path:
        return ""
    normalized = path.rstrip("/\\")
    label = normalized.replace("\\", "/").rsplit("/", 1)[-1]
    return label or normalized
