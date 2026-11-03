from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from nova.db.in_memory.agent import InMemoryAgentMixin
from nova.db.in_memory.memory import InMemoryMemoryMixin
from nova.db.in_memory.project import InMemoryProjectMixin
from nova.db.in_memory.schedule import InMemoryScheduleMixin
from nova.db.repository import NovaRepository
from nova.db.timestamps import to_milliseconds
from nova.scheduler.models import ScheduledJob
from nova.session.models import Message, MessageFilter

if TYPE_CHECKING:
    from nova.session.manager import SessionContext


class InMemoryRepository(
    InMemoryMemoryMixin,
    InMemoryScheduleMixin,
    InMemoryProjectMixin,
    InMemoryAgentMixin,
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

    async def save_session(self, session: SessionContext) -> None:
        now = int(time.time() * 1000)
        self._sessions[session.id] = {
            "id": session.id,
            "agent_key": getattr(session, "agent_key", "main"),
            "title": getattr(session, "title", None),
            "parent_id": getattr(session, "parent_id", None),
            "forked_from": getattr(session, "forked_from", None),
            "fork_point_message_id": getattr(session, "fork_point_message_id", None),
            "workspace_dir": getattr(session, "workspace_dir", None),
            "project_id": getattr(session, "project_id", None),
            "pinned": bool(getattr(session, "pinned", False)),
            "summary_goal": getattr(session, "summary_goal", None),
            "summary_accomplished": getattr(session, "summary_accomplished", None),
            "summary_remaining": getattr(session, "summary_remaining", None),
            "created_at": to_milliseconds(getattr(session, "created_at", now)),
            "updated_at": to_milliseconds(getattr(session, "updated_at", now)),
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

    async def update_session_route_if_changed(
        self,
        session_id: str,
        provider: str | None,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        wanted = (provider, model, reasoning_effort)
        current = (
            session.get("provider"),
            session.get("model"),
            session.get("reasoning_effort"),
        )
        if current == wanted:
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
        cache_read_tokens: int | None = None,
        provider_meta: dict[str, Any] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        error: str | None = None,
        variant: str | None = None,
        time_created: int | None = None,
        data: str | None = None,
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
            cache_read_tokens=cache_read_tokens,
            variant=variant,
            data=data,
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
