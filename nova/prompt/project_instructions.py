"""Project instruction files (AGENTS.md), discovered per session.

Two layers, matching the mainstream convention (Codex):

1. Global: ``$NOVA_HOME/AGENTS.override.md``, else ``$NOVA_HOME/AGENTS.md``.
   At most one file; it is the user's own config, like SOUL.md.
2. Project: from the git root down to the workspace, at most one file per
   directory: ``AGENTS.override.md``, else ``AGENTS.md``, else ``CLAUDE.md``.
   Without a git repo only the workspace directory itself is read.

Files concatenate global first, root-to-leaf after, so the file nearest the
workspace appears last and wins on conflict. The merged block is capped at
32 KiB; over the cap the root end is trimmed first, keeping the most specific
file alive.

Trust line: the global layer is the user's own and unscreened. The project
layer travels with the repo, so each file is screened for injection shapes
before it enters the prompt. Only the high-confidence categories run here --
``ignore_previous`` and ``role_hijack`` -- because a full screen would flag
legitimate conventions ("never reveal your system prompt" trips
``prompt_leak``). A flagged file is dropped individually, never taking the
rest of the chain down with it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from nova.prompt.threat_patterns import has_threats, scan_text

log = logging.getLogger(__name__)

GLOBAL_FILENAMES = ("AGENTS.override.md", "AGENTS.md")
PROJECT_FILENAMES = ("AGENTS.override.md", "AGENTS.md", "CLAUDE.md")
# Only categories a legitimate convention file should never contain. A full
# screen would flag normal safety rules ("never reveal your system prompt"
# trips prompt_leak) and drop the whole file.
PROJECT_THREAT_CATEGORIES = ["ignore_previous", "role_hijack"]
MAX_BLOCK_BYTES = 32 * 1024


@dataclass
class ProjectInstructions:
    """Merged instruction block plus where it came from.

    ``sources`` lists every file that contributed, root-to-leaf, so the prompt
    can show the user what is in effect. ``flagged`` lists project files that
    were dropped as potential injection, with the matched category.
    """

    text: str
    sources: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)


def _read_file(path: Path) -> str | None:
    """Read one file; unreadable means skipped, never fatal."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        log.warning("Skipping unreadable instruction file %s: %s", path, exc)
        return None
    if not text.strip():
        return None
    return text


def _first_present(directory: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _find_git_root(start: Path) -> Path | None:
    """Nearest ancestor (including self) containing ``.git``."""
    current = start
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def discover_project_instructions(workspace: str) -> ProjectInstructions | None:
    """Build the merged instruction block for a workspace.

    Runs once per workspace: the caller caches the system prompt per workspace
    and rebuilds on switch, so discovery cost stays off the hot path.
    """
    from nova.settings import get_settings

    home = get_settings().home
    blocks: list[tuple[str, str]] = []
    flagged: list[str] = []
    seen: set[Path] = set()

    def take(path: Path, screen: bool) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen:
            return
        seen.add(resolved)
        text = _read_file(path)
        if text is None:
            return
        if screen and has_threats(text, categories=PROJECT_THREAT_CATEGORIES):
            categories = sorted(
                {
                    hit["category"]
                    for hit in scan_text(text, categories=PROJECT_THREAT_CATEGORIES)
                }
            )
            flagged.append(f"{path} ({', '.join(categories)})")
            log.warning("Dropping flagged instruction file %s", path)
            return
        blocks.append((str(path), text))

    # Global layer: the user's own, at most one file, unscreened.
    global_hit = _first_present(home, GLOBAL_FILENAMES)
    if global_hit is not None:
        take(global_hit, screen=False)

    # Project layer: git root down to the workspace, at most one per level.
    try:
        workdir = Path(workspace).expanduser().resolve()
    except OSError:
        workdir = Path(workspace).expanduser()
    if workdir.is_dir():
        git_root = _find_git_root(workdir)
        if git_root is None:
            levels = [workdir]
        else:
            levels = []
            current = workdir
            while True:
                levels.append(current)
                if current == git_root:
                    break
                current = current.parent
            levels.reverse()
        for level in levels:
            hit = _first_present(level, PROJECT_FILENAMES)
            if hit is not None:
                take(hit, screen=True)

    if not blocks and not flagged:
        return None

    sources = [path for path, _ in blocks]
    chunks = [f"<!-- from {path} -->\n{text}" for path, text in blocks]
    notice = "[Earlier (broader) project instructions truncated at 32 KiB]"
    body = "\n\n".join(chunks)
    if len(body.encode("utf-8")) > MAX_BLOCK_BYTES:
        # Trim from the root end so the most specific file survives.
        kept: list[str] = []
        kept_sources: list[str] = []
        for (path, _), chunk in zip(reversed(blocks), reversed(chunks), strict=True):
            trial = "\n\n".join([chunk, *kept, notice])
            if kept and len(trial.encode("utf-8")) > MAX_BLOCK_BYTES:
                break
            kept.insert(0, chunk)
            kept_sources.insert(0, path)
        sources = kept_sources
        body = "\n\n".join([*kept, notice])

    return ProjectInstructions(text=body, sources=sources, flagged=flagged)
