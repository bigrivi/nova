"""Sessions for the in-memory repository."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from nova.db.repository import SessionStore
from nova.db.timestamps import to_milliseconds
from nova.session.models import Message

if TYPE_CHECKING:
    from nova.session.manager import SessionContext


class InMemorySessionMixin(SessionStore):
    """Session access for ``InMemoryRepository``."""

    _sessions: dict[str, dict[str, Any]]
    _messages: dict[str, Message]

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

    async def update_session_compacted_at(
        self, session_id: str, timestamp: int
    ) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["compacted_at"] = timestamp
