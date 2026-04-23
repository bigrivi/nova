from __future__ import annotations

from datetime import datetime
from typing import Optional

from nova.db import database
from nova.db.database import MessageFilter


class SessionManager:
    def __init__(
        self,
        *,
        agent: object,
        display: object,
    ) -> None:
        self._agent = agent
        self._display = display
        self.current_id: Optional[str] = None
        self._cached_sessions: list[dict] = []

    def get_load_completion_candidates(self) -> list[dict]:
        return [session for session in self._cached_sessions if isinstance(session, dict)]

    def reset(self) -> None:
        self.current_id = None

    async def show_sessions(self) -> None:
        db = await database.ensure_db()
        sessions = await db.get_all_sessions()

        if not sessions:
            self._display.info("No sessions found")
            return

        self._display.info(f"Sessions ({len(sessions)} total)")
        self._cached_sessions = sessions
        for i, sess in enumerate(sessions, 1):
            title = sess.get("title") or "Untitled"
            is_active = sess["id"] == self.current_id
            marker = " (active)" if is_active else ""
            updated = sess.get("updated_at", 0) // 1000
            time_str = datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M")
            self._display.info(f"  {i}. {title}{marker}")
            self._display.info(f"      {sess['id'][:8]}... - {time_str}")

        self._display.info("Type /load <n> to load a session")

    async def load_session(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._cached_sessions):
            self._display.info("Invalid session index")
            return

        sess = self._cached_sessions[idx]
        session_id = sess["id"]
        loaded = await self._agent.session.load_session(session_id)
        if loaded is None:
            self._display.error("Failed to load session")
            return

        db = await database.ensure_db()
        history = await db.get_messages(
            session_id,
            MessageFilter(include_compacted=True),
        )
        self.current_id = session_id
        title = sess.get("title") or "Untitled"
        self._display.info(f"Loaded session: {title}")
        if not history:
            self._display.info("No messages found")
            return
        self._display.print_history_transcript(history)

    def set_cached_sessions_for_tests(self, sessions: list[dict]) -> None:
        self._cached_sessions = sessions

    def get_cached_sessions_for_tests(self) -> list[dict]:
        return self._cached_sessions
