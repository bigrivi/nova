"""Sub-agent permission posture.

A posture is the domain-neutral safety envelope a user picks when creating a
sub-agent. It maps to a tool allowlist the runtime enforces at registration and
dispatch. Nova is a general-purpose agent, so there are no built-in role
identities here -- only the posture (what a sub-agent is *allowed* to touch);
the sub-agent's behaviour comes from its own user-authored instructions.
"""

from __future__ import annotations

READ_ONLY = "read_only"
FULL = "full"
POSTURES: frozenset[str] = frozenset({READ_ONLY, FULL})
DEFAULT_POSTURE = FULL

READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "read",
        "glob",
        "grep",
        "web_search",
        "web_fetch",
        "read_image",
        "todo_write",
        "search_memory",
        "list_memories",
        "list_skills",
        "load_skill",
    }
)


def normalize_posture(posture: str | None) -> str:
    value = (posture or "").strip().lower()
    return value if value in POSTURES else DEFAULT_POSTURE


def allowed_tools_for(posture: str | None) -> frozenset[str] | None:
    """Return the tool allowlist for *posture*; ``None`` means no restriction."""
    return READ_ONLY_TOOLS if normalize_posture(posture) == READ_ONLY else None
