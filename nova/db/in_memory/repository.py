from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from nova.db.in_memory.agent import InMemoryAgentMixin
from nova.db.in_memory.memory import InMemoryMemoryMixin
from nova.db.in_memory.message import InMemoryMessageMixin
from nova.db.in_memory.project import InMemoryProjectMixin
from nova.db.in_memory.schedule import InMemoryScheduleMixin
from nova.db.in_memory.session import InMemorySessionMixin
from nova.db.repository import NovaRepository
from nova.scheduler.models import ScheduledJob
from nova.session.models import Message

if TYPE_CHECKING:
    pass


class InMemoryRepository(
    InMemoryMemoryMixin,
    InMemoryScheduleMixin,
    InMemoryProjectMixin,
    InMemoryAgentMixin,
    InMemoryMessageMixin,
    InMemorySessionMixin,
    NovaRepository,
):
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._projects: dict[str, dict[str, Any]] = {}
        self._messages: dict[str, Message] = {}
        self._schedules: dict[str, ScheduledJob] = {}
        self._leases: dict[str, dict[str, Any]] = {}
        self._agents: dict[str, dict[str, Any]] = {
            "main": {
                "key": "main",
                "name": "Main",
                "description": "",
                "model": "gpt-4o",
                "provider": "openai",
                "tools": None,
                "workspace_dir": None,
                "parent_id": None,
                "created_at": int(time.time() * 1000),
                "updated_at": int(time.time() * 1000),
            }
        }
        self._agent_parents: set[tuple[str, str]] = set()
        self._memories: dict[str, dict[str, Any]] = {}
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False
