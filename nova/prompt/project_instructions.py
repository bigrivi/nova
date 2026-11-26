"""Nova settings adapter for portable project-instruction discovery."""

from __future__ import annotations

from novakit.prompt.project_instructions import (
    GLOBAL_FILENAMES,
    MAX_BLOCK_BYTES,
    PROJECT_FILENAMES,
    PROJECT_THREAT_CATEGORIES,
    ProjectInstructionConfig,
    ProjectInstructions,
)
from novakit.prompt.project_instructions import (
    discover_project_instructions as _discover_project_instructions,
)

from nova.settings import get_settings


def discover_project_instructions(workspace: str) -> ProjectInstructions | None:
    """Discover instructions using Nova's host-owned global directory.

    Args:
        workspace: Workspace directory whose instruction chain should be loaded.

    Returns:
        Merged instructions and provenance, or None when nothing was found.
    """
    return _discover_project_instructions(
        workspace,
        ProjectInstructionConfig(global_dir=get_settings().home),
    )


__all__ = [
    "GLOBAL_FILENAMES",
    "MAX_BLOCK_BYTES",
    "PROJECT_FILENAMES",
    "PROJECT_THREAT_CATEGORIES",
    "ProjectInstructionConfig",
    "ProjectInstructions",
    "discover_project_instructions",
]
