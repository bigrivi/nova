import asyncio
import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid

from nova.db.database import get_db, ensure_db, Message
from nova.llm import Message as LLMMessage


class SessionStatus(Enum):
    ACTIVE = "active"
    IDLE = "idle"
    TERMINATED = "terminated"


@dataclass
class SessionContext:
    id: str
    created_at: datetime
    updated_at: datetime
    status: SessionStatus = SessionStatus.ACTIVE
    metadata: dict = field(default_factory=dict)
    title: Optional[str] = None
    parent_id: Optional[str] = None
    summary_goal: Optional[str] = None
    summary_accomplished: Optional[str] = None
    summary_remaining: Optional[str] = None
    compacted_at: Optional[int] = None
    message_count: int = 0
    turn_count: int = 0

    @classmethod
    def create(cls) -> "SessionContext":
        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
        )


_current_session: ContextVar[Optional[SessionContext]] = ContextVar(
    "current_session", default=None)


class SessionManager:
    def __init__(self):
        self._lock = asyncio.Lock()

    def get_current_session(self) -> Optional[SessionContext]:
        return _current_session.get()

    def set_current_session(self, session: Optional[SessionContext]) -> None:
        _current_session.set(session)

    async def create_session(
        self,
        metadata: Optional[dict] = None,
        persist: bool = True,
        first_message: str = None,
    ) -> SessionContext:
        session = SessionContext.create()
        session.metadata = metadata or {}
        session.title = self._generate_title(first_message)
        self.set_current_session(session)
        if persist:
            await self.save_session(session)
        return session

    def _generate_title(self, user_message: str = None) -> str:
        """Generate a session title from the user's message."""
        if user_message:
            msg = user_message.strip()
            if len(msg) > 50:
                msg = msg[:47] + "..."
            return msg
        return "New Session"

    async def update_session_title(self, session_id: str, title: str) -> None:
        """Update the session title."""
        session = self.get_current_session()
        if session and session.id == session_id:
            session.title = title
            await self.save_session(session)

    async def save_session(self, session: SessionContext) -> None:
        async with self._lock:
            db = await ensure_db()
            await db.save_session(session)

    async def load_session(self, session_id: str) -> Optional[SessionContext]:
        async with self._lock:
            db = await ensure_db()
            session_data = await db.get_session(session_id)
            if session_data:
                ctx = SessionContext(
                    id=session_data["id"],
                    title=session_data.get("title"),
                    created_at=session_data["created_at"],
                    updated_at=session_data["updated_at"],
                    status=SessionStatus(session_data.get("status", "active")),
                    metadata=json.loads(session_data["metadata"]) if session_data.get(
                        "metadata") else {},
                    parent_id=session_data.get("parent_id"),
                    summary_goal=session_data.get("summary_goal"),
                    summary_accomplished=session_data.get(
                        "summary_accomplished"),
                    summary_remaining=session_data.get("summary_remaining"),
                    compacted_at=session_data.get("compacted_at"),
                    message_count=session_data.get("message_count", 0),
                    turn_count=session_data.get("turn_count", 0),
                )
                self.set_current_session(ctx)
                return ctx
            return None

    async def add_message(
        self,
        role: str,
        content: str,
        tool_calls: Optional[list] = None,
        tool_call_id: Optional[str] = None,
    ) -> Message:
        session = self.get_current_session()
        if not session:
            raise RuntimeError("No active session")

        async with self._lock:
            db = await ensure_db()
            msg = await db.add_message(
                session_id=session.id,
                role=role,
                content=content,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )
            session.updated_at = datetime.now(timezone.utc)
            session.turn_count += 1
            return msg

    async def rollback_messages(
        self,
        message_ids: list[str],
        session_id: Optional[str] = None,
    ) -> int:
        sid = session_id or (self.get_current_session(
        ).id if self.get_current_session() else None)
        if not sid or not message_ids:
            return 0

        async with self._lock:
            db = await ensure_db()
            deleted_count = await db.delete_messages(sid, message_ids)
            session = self.get_current_session()
            if session and session.id == sid and deleted_count:
                session.updated_at = datetime.now(timezone.utc)
                session.turn_count = max(0, session.turn_count - deleted_count)
            return deleted_count

    async def get_messages(
        self,
        session_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Message]:
        sid = session_id or (self.get_current_session(
        ).id if self.get_current_session() else None)
        if not sid:
            return []
        async with self._lock:
            db = await ensure_db()
            return await db.get_messages(sid, limit=limit)

    async def compress_history(self, target_count: int = 50) -> None:
        session = self.get_current_session()
        if not session:
            return
        async with self._lock:
            db = await ensure_db()
            await db.compress_messages(session.id, target_count)

    async def pause(self, session_id: str) -> None:
        """Pause a session."""
        session = self.get_current_session()
        if session and session.id == session_id:
            session.status = SessionStatus.IDLE
            await self.save_session(session)

    async def resume(self, session_id: str) -> Optional[SessionContext]:
        """Resume a session."""
        async with self._lock:
            db = await ensure_db()
            session_data = await db.get_session(session_id)
            if session_data:
                session = SessionContext(
                    id=session_data["id"],
                    title=session_data.get("title"),
                    created_at=session_data["created_at"],
                    updated_at=session_data["updated_at"],
                    status=SessionStatus.ACTIVE,
                    metadata=json.loads(session_data["metadata"]) if session_data.get(
                        "metadata") else {},
                    parent_id=session_data.get("parent_id"),
                    summary_goal=session_data.get("summary_goal"),
                    summary_accomplished=session_data.get(
                        "summary_accomplished"),
                    summary_remaining=session_data.get("summary_remaining"),
                    compacted_at=session_data.get("compacted_at"),
                    message_count=session_data.get("message_count", 0),
                    turn_count=session_data.get("turn_count", 0),
                )
                self.set_current_session(session)
                await self.save_session(session)
                return session
            return None


_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


async def close_session_manager() -> None:
    global _manager
    if _manager is not None:
        from nova.db.database import close_db
        await close_db()
        _manager = None
