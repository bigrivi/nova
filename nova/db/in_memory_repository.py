from __future__ import annotations

import json
import time
import uuid
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nova.db.repository import NovaRepository
from nova.memory.models import MemoryRecord, MemorySearchFilters
from nova.project.models import Project
from nova.scheduler.models import ScheduledJob
from nova.session.models import Message, MessageFilter

if TYPE_CHECKING:
    from nova.session.manager import SessionContext


class InMemoryRepository(NovaRepository):
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

    async def save_session(self, session: SessionContext) -> None:
        now = int(time.time() * 1000)
        self._sessions[session.id] = {
            "id": session.id,
            "agent_key": getattr(session, "agent_key", "main"),
            "title": getattr(session, "title", None),
            "parent_id": getattr(session, "parent_id", None),
            "workspace_dir": getattr(session, "workspace_dir", None),
            "project_id": getattr(session, "project_id", None),
            "pinned": bool(getattr(session, "pinned", False)),
            "summary_goal": getattr(session, "summary_goal", None),
            "summary_accomplished": getattr(session, "summary_accomplished", None),
            "summary_remaining": getattr(session, "summary_remaining", None),
            "created_at": self._milliseconds(getattr(session, "created_at", now)),
            "updated_at": self._milliseconds(getattr(session, "updated_at", now)),
            "compacted_at": getattr(session, "compacted_at", None),
            "message_count": getattr(session, "message_count", 0),
            "turn_count": getattr(session, "turn_count", 0),
            "metadata": json.dumps(getattr(session, "metadata", None))
            if getattr(session, "metadata", None)
            else None,
            "provider": getattr(session, "provider", None),
            "model": getattr(session, "model", None),
            "reasoning_effort": getattr(session, "reasoning_effort", None),
        }

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        return dict(session) if session else None

    async def update_session_title(self, session_id: str, title: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session["title"] = title
        return True

    async def update_session_title_if_matches(
        self, session_id: str, title: str, expected_title: str
    ) -> bool:
        session = self._sessions.get(session_id)
        if session is None or session.get("title") != expected_title:
            return False
        session["title"] = title
        return True

    async def set_session_workspace(
        self, session_id: str, workspace_dir: str | None
    ) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session["workspace_dir"] = workspace_dir
        return True

    async def set_session_pinned(self, session_id: str, pinned: bool) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session["pinned"] = pinned
        return True

    async def set_session_route(
        self,
        session_id: str,
        provider: str | None,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session["provider"] = provider
        session["model"] = model
        session["reasoning_effort"] = reasoning_effort
        return True

    async def set_session_project(
        self, session_id: str, project_id: str | None
    ) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session["project_id"] = project_id
        return True

    async def save_project(self, project: Project) -> None:
        now = int(time.time() * 1000)
        self._projects[project.id] = {
            "id": project.id,
            "name": project.name,
            "path": getattr(project, "path", None),
            "created_at": self._milliseconds(getattr(project, "created_at", now)),
            "updated_at": self._milliseconds(getattr(project, "updated_at", now)),
        }

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        project = self._projects.get(project_id)
        return dict(project) if project else None

    async def list_projects(self) -> list[dict[str, Any]]:
        projects = sorted(
            self._projects.values(),
            key=lambda item: item["updated_at"],
            reverse=True,
        )
        return [dict(project) for project in projects]

    async def find_projects_by_path(self, path: str) -> list[dict[str, Any]]:
        projects = [
            project for project in self._projects.values() if project["path"] == path
        ]
        projects.sort(key=lambda item: item["updated_at"], reverse=True)
        return [dict(project) for project in projects]

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project and detach its sessions. Sessions are kept."""
        if project_id not in self._projects:
            return False
        del self._projects[project_id]
        for session in self._sessions.values():
            if session.get("project_id") == project_id:
                session["project_id"] = None
        return True

    async def delete_session(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        for message_id in [
            m.id for m in self._messages.values() if m.session_id == session_id
        ]:
            del self._messages[message_id]
        return True

    async def get_all_sessions(
        self, limit: int | None = None, agent_key: str | None = None
    ) -> list[dict[str, Any]]:
        sessions = list(self._sessions.values())
        if agent_key:
            sessions = [s for s in sessions if s["agent_key"] == agent_key]
        sessions.sort(key=lambda item: item["updated_at"], reverse=True)
        if limit is None:
            return [dict(session) for session in sessions]
        return [dict(session) for session in sessions[:limit]]

    async def get_sessions_by_parent_id(
        self, parent_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        sessions = [s for s in self._sessions.values() if s["parent_id"] == parent_id]
        sessions.sort(key=lambda item: item["created_at"], reverse=True)
        return [dict(session) for session in sessions[:limit]]

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        summary: bool = False,
        images: list[str] | None = None,
        reasoning_content: str | None = None,
        group_id: str | None = None,
        reasoning_elapsed_ms: int | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        provider_meta: dict[str, Any] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        error: str | None = None,
        variant: str | None = None,
        time_created: int | None = None,
    ) -> Message:
        now = int(time.time() * 1000)
        message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            summary=1 if summary else 0,
            images=images,
            reasoning_content=reasoning_content,
            group_id=group_id,
            reasoning_elapsed_ms=reasoning_elapsed_ms,
            error=error,
            provider_meta=provider_meta,
            model=model,
            reasoning_effort=reasoning_effort,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            variant=variant,
            # A caller may place a row at an earlier point in time (compaction
            # summaries do); updated_at below still tracks insertion order so
            # sidebar ordering is unaffected.
            time_created=now if time_created is None else time_created,
        )
        self._messages[message.id] = message
        session = self._sessions.get(session_id)
        if session:
            session["updated_at"] = now
            session["message_count"] += 1
        return message

    async def get_messages(
        self, session_id: str, msg_filter: MessageFilter | None = None
    ) -> list[Message]:
        filter_value = msg_filter or MessageFilter()
        messages = [m for m in self._messages.values() if m.session_id == session_id]
        messages.sort(key=lambda message: message.time_created)
        if not filter_value.include_compacted:
            messages = [m for m in messages if m.compacted == 0]
        if filter_value.exclude_tool_role:
            messages = [m for m in messages if m.role != "tool"]
        if filter_value.only_non_summary:
            messages = [m for m in messages if m.summary == 0]
        if filter_value.limit is not None:
            messages = messages[: filter_value.limit]
        return messages

    async def compress_messages(self, session_id: str, target_count: int = 50) -> None:
        messages = await self.get_messages(
            session_id, MessageFilter(include_compacted=True)
        )
        if len(messages) <= target_count:
            return
        delete_count = len(messages) - target_count
        for message in [m for m in messages if m.summary == 0][:delete_count]:
            message.summary = 1
        session = self._sessions.get(session_id)
        if session:
            session["compacted_at"] = int(time.time() * 1000)

    async def mark_messages_compacted(self, session_id: str) -> None:
        for message in self._messages.values():
            if (
                message.session_id == session_id
                and message.compacted == 0
                and message.summary == 0
            ):
                message.compacted = 1

    async def mark_messages_compacted_by_ids(
        self, session_id: str, message_ids: list[str]
    ) -> None:
        for message_id in message_ids:
            message = self._messages.get(message_id)
            if message and message.session_id == session_id:
                message.compacted = 1

    async def update_session_compacted_at(
        self, session_id: str, timestamp: int
    ) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["compacted_at"] = timestamp

    async def update_message_content(self, message_id: str, content: str) -> None:
        message = self._messages.get(message_id)
        if message:
            message.content = content
            message.data = content

    async def delete_messages(self, session_id: str, message_ids: list[str]) -> int:
        selected = [
            m
            for m in self._messages.values()
            if m.session_id == session_id and m.id in message_ids
        ]
        for message in selected:
            del self._messages[message.id]
        session = self._sessions.get(session_id)
        if session:
            session["message_count"] = max(0, session["message_count"] - len(selected))
            session["updated_at"] = int(time.time() * 1000)
        return len(selected)

    async def list_agents(self) -> list[dict[str, Any]]:
        return sorted(
            (dict(agent) for agent in self._agents.values()),
            key=lambda item: item["name"],
        )

    async def get_agent(self, key: str) -> dict[str, Any] | None:
        agent = self._agents.get(key)
        return dict(agent) if agent else None

    async def save_agent(self, agent: dict[str, Any]) -> None:
        self._agents[agent["key"]] = dict(agent)

    async def get_child_agents(self, parent_key: str) -> list[dict[str, Any]]:
        child_keys = {
            child for child, parent in self._agent_parents if parent == parent_key
        }
        return [
            agent for agent in await self.list_agents() if agent["key"] in child_keys
        ]

    async def get_agent_parents(self, child_key: str) -> list[str]:
        return [parent for child, parent in self._agent_parents if child == child_key]

    async def get_agent_children(self, parent_key: str) -> list[str]:
        return [child for child, parent in self._agent_parents if parent == parent_key]

    async def set_agent_parents(self, child_key: str, parent_keys: list[str]) -> None:
        self._agent_parents = {
            (child, parent)
            for child, parent in self._agent_parents
            if child != child_key
        }
        self._agent_parents.update((child_key, parent) for parent in parent_keys)

    async def add_agent_parent(self, child_key: str, parent_key: str) -> None:
        self._agent_parents.add((child_key, parent_key))

    async def remove_agent_parent(self, child_key: str, parent_key: str) -> None:
        self._agent_parents.discard((child_key, parent_key))

    async def delete_agent(self, key: str) -> bool:
        if key not in self._agents:
            return False
        del self._agents[key]
        self._agent_parents = {
            (child, parent)
            for child, parent in self._agent_parents
            if child != key and parent != key
        }
        for session_id in [
            s["id"] for s in self._sessions.values() if s["agent_key"] == key
        ]:
            await self.delete_session(session_id)
        return True

    async def save_memory(self, record: MemoryRecord) -> None:
        self._memories[record.id] = {
            "id": record.id,
            "key": record.key,
            "scope": record.scope,
            "session_id": record.session_id,
            "owner_agent_key": record.owner_agent_key,
            "memory_type": record.memory_type,
            "content": record.content,
            "summary": record.summary,
            "tags": json.dumps(record.tags) if record.tags else None,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def get_memory_by_key(
        self,
        key: str,
        scope: str,
        session_id: str | None = None,
        owner_agent_key: str | None = None,
    ) -> dict[str, Any] | None:
        for memory in self._memories.values():
            if memory["key"] != key or memory["scope"] != scope:
                continue
            if memory.get("owner_agent_key") != owner_agent_key:
                continue
            if scope == "session" and session_id is None:
                continue
            if scope != "session" or memory["session_id"] == session_id:
                return dict(memory)
        return None

    async def list_memories(
        self, filters: MemorySearchFilters
    ) -> list[dict[str, Any]]:
        memories = list(self._memories.values())
        if filters.scope != "all":
            memories = [m for m in memories if m["scope"] == filters.scope]
        if filters.memory_type:
            memories = [m for m in memories if m["memory_type"] == filters.memory_type]
        if filters.session_id:
            memories = [
                m
                for m in memories
                if m["scope"] != "session" or m["session_id"] == filters.session_id
            ]
        owner_agent_key = getattr(filters, "owner_agent_key", None)
        if owner_agent_key:
            memories = [
                m
                for m in memories
                if m.get("owner_agent_key") is None
                or m.get("owner_agent_key") == owner_agent_key
            ]
        else:
            memories = [m for m in memories if m.get("owner_agent_key") is None]
        memories.sort(key=lambda item: item["updated_at"], reverse=True)
        return [dict(memory) for memory in memories[: filters.limit]]

    async def delete_memory_by_id(self, memory_id: str) -> int:
        return 1 if self._memories.pop(memory_id, None) is not None else 0

    async def delete_memories_by_session(self, session_id: str) -> int:
        ids = [
            key
            for key, memory in self._memories.items()
            if memory["session_id"] == session_id
        ]
        for memory_id in ids:
            del self._memories[memory_id]
        return len(ids)

    async def list_memories_by_session(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        memories = [
            dict(m) for m in self._memories.values() if m["session_id"] == session_id
        ]
        memories.sort(key=lambda item: item["updated_at"], reverse=True)
        return memories

    async def delete_memory_by_key(
        self,
        key: str,
        scope: str,
        session_id: str | None = None,
        owner_agent_key: str | None = None,
    ) -> int:
        memory = await self.get_memory_by_key(key, scope, session_id, owner_agent_key)
        return await self.delete_memory_by_id(memory["id"]) if memory else 0

    @staticmethod
    def _milliseconds(value: datetime | int | float) -> int:
        return (
            int(value.timestamp() * 1000) if hasattr(value, "timestamp") else int(value)
        )

    def _coerce_job(self, job: ScheduledJob | dict[str, Any]) -> ScheduledJob:
        if isinstance(job, dict):
            return ScheduledJob.from_dict(job)
        return replace(job)

    async def create_schedule(
        self, job: ScheduledJob | dict[str, Any]
    ) -> ScheduledJob:
        from nova.scheduler.schedule import next_fire_time

        record = self._coerce_job(job)
        now = int(time.time() * 1000)
        if not record.id:
            record.id = str(uuid.uuid4())
        if not record.created_at:
            record.created_at = now
        record.updated_at = now
        if record.next_run_at is None and record.enabled:
            try:
                record.next_run_at = next_fire_time(record, now)
            except ValueError:
                record.next_run_at = None
        self._schedules[record.id] = replace(record)
        return replace(record)

    async def get_schedule(self, job_id: str) -> ScheduledJob | None:
        job = self._schedules.get(job_id)
        return replace(job) if job is not None else None

    async def list_schedules(
        self, enabled_only: bool = False
    ) -> list[ScheduledJob]:
        jobs = list(self._schedules.values())
        if enabled_only:
            jobs = [job for job in jobs if job.enabled]
        jobs.sort(key=lambda job: job.updated_at, reverse=True)
        return [replace(job) for job in jobs]

    async def update_schedule(self, job: ScheduledJob | dict[str, Any]) -> bool:
        record = self._coerce_job(job)
        if record.id not in self._schedules:
            return False
        if not record.updated_at:
            record.updated_at = int(time.time() * 1000)
        self._schedules[record.id] = replace(record)
        return True

    async def delete_schedule(self, job_id: str) -> bool:
        return self._schedules.pop(job_id, None) is not None

    async def due_schedules(
        self, now_ms: int, limit: int = 100
    ) -> list[ScheduledJob]:
        due = [
            job
            for job in self._schedules.values()
            if job.enabled and job.next_run_at is not None and job.next_run_at <= now_ms
        ]
        due.sort(key=lambda job: job.next_run_at or 0)
        return [replace(job) for job in due[:limit]]

    async def get_scheduler_lease(
        self, lease_id: str = "primary"
    ) -> dict[str, Any] | None:
        lease = self._leases.get(lease_id)
        return dict(lease) if lease else None

    async def acquire_scheduler_lease(
        self, lease_id: str, owner: str, expires_at_ms: int, now_ms: int
    ) -> bool:
        """Take or renew the lease when free, expired, or already ours."""
        current = self._leases.get(lease_id)
        if (
            current is None
            or current["owner"] == owner
            or current["expires_at"] <= now_ms
        ):
            self._leases[lease_id] = {
                "id": lease_id,
                "owner": owner,
                "expires_at": expires_at_ms,
            }
            return True
        return False

    async def release_scheduler_lease(
        self, lease_id: str, owner: str, now_ms: int
    ) -> bool:
        """Expire the lease when *owner* holds it, so a restart resumes at once."""
        current = self._leases.get(lease_id)
        if current is None or current["owner"] != owner:
            return False
        current["expires_at"] = now_ms
        return True
