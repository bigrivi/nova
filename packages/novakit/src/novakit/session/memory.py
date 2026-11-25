"""Pure in-memory session storage for standalone novakit users.

Keeps every session and message in the instance's own dicts. ``persist=True``
only means "kept in this object": nothing is written to disk, no workspace
directory is created, and no environment variable is read.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextvars import ContextVar
from typing import Any

from novakit.constants import DEFAULT_AGENT_KEY
from novakit.session.models import Message, SessionContext
from novakit.session.protocol import SessionProtocol


def _default_title(first_message: str | None = None) -> str:
    if first_message and first_message.strip():
        return first_message.strip()
    return "New Session"


class InMemorySession(SessionProtocol):
    """Per-instance in-memory implementation of :class:`SessionProtocol`."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, SessionContext] = {}
        self._messages: dict[str, list[Message]] = {}
        self._current: ContextVar[SessionContext | None] = ContextVar(
            f"novakit-inmemory-current-{id(self)}", default=None
        )

    def get_current_session(self) -> SessionContext | None:
        """Return the session running in this task, if any."""
        return self._current.get()

    def set_current_session(self, session: SessionContext | None) -> None:
        """Point this task at *session* without touching other instances."""
        self._current.set(session)

    async def create_session(
        self,
        *,
        persist: bool = True,
        first_message: str | None = None,
        agent_key: str = DEFAULT_AGENT_KEY,
        metadata: dict | None = None,
        parent_id: str | None = None,
        workspace_dir: str | None = None,
        project_id: str | None = None,
    ) -> SessionContext:
        """Create a session and make it current; ``persist`` only keeps memory."""
        _ = persist
        now = int(time.time() * 1000)
        session = SessionContext.create(agent_key=agent_key)
        session.metadata = metadata or {}
        session.title = _default_title(first_message)
        session.parent_id = parent_id
        session.workspace_dir = workspace_dir
        session.project_id = project_id
        session.message_count = 0
        session.turn_count = 0
        session.updated_at = now
        async with self._lock:
            self._sessions[session.id] = session
            self._messages.setdefault(session.id, [])
        self.set_current_session(session)
        return session

    async def load_session(self, session_id: str) -> SessionContext | None:
        """Make the stored session current, or return None when unknown."""
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return None
        self.set_current_session(session)
        return session

    async def apply_generated_title(
        self, session_id: str, title: str, expected_title: str
    ) -> bool:
        """Store a background-generated title unless the user renamed first."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.title != expected_title:
                return False
            session.title = title
            session.updated_at = int(time.time() * 1000)
        current = self.get_current_session()
        if current is not None and current.id == session_id:
            current.title = title
        return True

    async def get_messages(
        self,
        session_id: str | None = None,
        limit: int | None = None,
        last_n: int | None = None,
    ) -> list[Message]:
        """Return non-compacted messages oldest-first, with limit/last_n."""
        current = self.get_current_session()
        sid = session_id or (current.id if current else None)
        if not sid:
            return []
        async with self._lock:
            stored = list(self._messages.get(sid, []))
        visible = [m for m in stored if m.compacted == 0]
        visible.sort(key=lambda message: message.time_created)
        if last_n is not None:
            return visible[-last_n:] if last_n else []
        if limit is not None:
            return visible[:limit]
        return visible

    async def rollback_messages(
        self, message_ids: list[str], session_id: str | None = None
    ) -> int:
        """Delete the named messages and fold the counts back."""
        current = self.get_current_session()
        sid = session_id or (current.id if current else None)
        if not sid or not message_ids:
            return 0
        async with self._lock:
            stored = self._messages.get(sid, [])
            kept = [m for m in stored if m.id not in message_ids]
            deleted = len(stored) - len(kept)
            if not deleted:
                return 0
            self._messages[sid] = kept
            now = int(time.time() * 1000)
            session = self._sessions.get(sid)
            if session is not None:
                session.message_count = max(0, session.message_count - deleted)
                session.turn_count = max(0, session.turn_count - deleted)
                session.updated_at = now
            if current is not None and current is not session and current.id == sid:
                current.message_count = max(0, current.message_count - deleted)
                current.turn_count = max(0, current.turn_count - deleted)
                current.updated_at = now
            return deleted

    async def add_message(
        self,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        images: list[str] | None = None,
        reasoning_content: str | None = None,
        group_id: str | None = None,
        reasoning_elapsed_ms: int | None = None,
        error: str | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        cache_read_tokens: int | None = None,
        cost: float | None = None,
        provider_meta: dict[str, Any] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        variant: str | None = None,
        data: str | None = None,
    ) -> Message:
        """Append a message to the current session and bump its counters."""
        session = self.get_current_session()
        if session is None:
            raise RuntimeError("No active session")
        now = int(time.time() * 1000)
        message = Message(
            id=str(uuid.uuid4()),
            session_id=session.id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            images=images,
            reasoning_content=reasoning_content,
            group_id=group_id,
            reasoning_elapsed_ms=reasoning_elapsed_ms,
            error=error,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cache_read_tokens=cache_read_tokens,
            cost=cost,
            provider_meta=provider_meta,
            model=model,
            reasoning_effort=reasoning_effort,
            variant=variant,
            data=data,
            time_created=now,
        )
        async with self._lock:
            self._messages.setdefault(session.id, []).append(message)
            stored = self._sessions.get(session.id)
            if stored is not None and stored is not session:
                stored.message_count += 1
                stored.turn_count += 1
                stored.updated_at = now
            session.message_count += 1
            session.turn_count += 1
            session.updated_at = now
        return message


__all__ = ["InMemorySession"]
