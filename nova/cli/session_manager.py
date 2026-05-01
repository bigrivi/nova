from __future__ import annotations

from datetime import datetime
from typing import Optional

from nova.db import database
from nova.session.history_projection import get_user_visible_history


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

    def set_agent(self, agent: object) -> None:
        self._agent = agent

    def reset(self) -> None:
        self.current_id = None

    async def list_sessions(self) -> list[dict]:
        db = await database.ensure_db()
        sessions = await db.get_all_sessions()
        self._cached_sessions = [session for session in sessions if isinstance(session, dict)]
        return self._cached_sessions

    async def show_sessions(self) -> None:
        sessions = await self.list_sessions()

        if not sessions:
            self._display.info("No sessions found")
            return

        self._display.info(f"Sessions ({len(sessions)} total)")
        for i, sess in enumerate(sessions, 1):
            title = sess.get("title") or "Untitled"
            is_active = sess["id"] == self.current_id
            marker = " (active)" if is_active else ""
            updated = sess.get("updated_at", 0) // 1000
            time_str = datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M")
            self._display.info(f"  {i}. {title}{marker}")
            self._display.info(f"      {sess['id'][:8]}... - {time_str}")

    async def load_session_by_id(self, session_id: str) -> None:
        sess = next(
            (session for session in self._cached_sessions if session.get("id") == session_id),
            None,
        )
        if sess is None:
            sessions = await self.list_sessions()
            sess = next(
                (session for session in sessions if session.get("id") == session_id),
                None,
            )
        if sess is None:
            self._display.error("Session not found")
            return

        loaded = await self._agent.session.load_session(session_id)
        if loaded is None:
            self._display.error("Failed to load session")
            return

        db = await database.ensure_db()
        visible_history = await get_user_visible_history(db, session_id)
        self.current_id = session_id
        title = sess.get("title") or "Untitled"
        self._display.info(f"Loaded session: {title}")
        if not visible_history:
            self._display.info("No messages found")
            return
        self._display.print_history_transcript(visible_history)

    def set_cached_sessions_for_tests(self, sessions: list[dict]) -> None:
        self._cached_sessions = sessions

    def get_cached_sessions_for_tests(self) -> list[dict]:
        return self._cached_sessions
