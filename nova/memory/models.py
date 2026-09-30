"""
Memory domain models.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

VALID_MEMORY_SCOPES = {"user", "project", "session", "agent"}
VALID_MEMORY_TYPES = {"fact", "preference", "decision", "context"}


@dataclass
class MemoryRecord:
    id: str
    key: str
    scope: str
    memory_type: str
    content: str
    summary: str
    tags: list[str] = field(default_factory=list)
    session_id: str | None = None
    owner_agent_key: str | None = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class MemoryWriteRequest:
    key: str
    content: str
    summary: str
    scope: str
    memory_type: str
    tags: list[str] = field(default_factory=list)
    session_id: str | None = None
    owner_agent_key: str | None = None


@dataclass
class MemorySearchFilters:
    query: str = ""
    scope: str = "all"
    memory_type: str | None = None
    session_id: str | None = None
    owner_agent_key: str | None = None
    limit: int = 10
