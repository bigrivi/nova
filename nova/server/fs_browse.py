"""Read-only local directory browsing for the workspace picker.

Nova's backend is local to the user's machine, so the folder picker lists
real directories from the local filesystem and returns absolute paths. Only
directories are returned (a workspace is a folder), and only names/paths —
never file contents.
"""

from __future__ import annotations

from pathlib import Path

from nova.server.schemas import DirectoryEntry, DirectoryListing


def list_directory(path: str | None = None) -> DirectoryListing:
    base = Path(path).expanduser() if path and path.strip() else Path.home()
    base = base.resolve()

    if not base.exists():
        raise FileNotFoundError(f"Directory not found: {base}")
    if not base.is_dir():
        raise NotADirectoryError(f"Not a directory: {base}")

    entries: list[DirectoryEntry] = []
    try:
        children = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except PermissionError as exc:
        raise PermissionError(f"Permission denied: {base}") from exc

    for child in children:
        try:
            if child.is_dir():
                entries.append(DirectoryEntry(name=child.name, path=str(child)))
        except OSError:
            continue

    parent = str(base.parent) if base.parent != base else None
    return DirectoryListing(path=str(base), parent=parent, entries=entries)
