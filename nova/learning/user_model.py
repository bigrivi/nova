"""User profile modeling across sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

MAX_RENDER_CHARS = 500


@dataclass
class UserProfile:
    user_id: str
    preferences: list[str] = field(default_factory=list)
    working_style: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class UserModel:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Any = None

    async def connect(self) -> None:
        import aiosqlite

        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS user_profiles "
            "(user_id TEXT PRIMARY KEY, profile_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def load(self, user_id: str) -> UserProfile:
        if self._conn is None:
            await self.connect()
        cursor = await self._conn.execute(
            "SELECT profile_json FROM user_profiles WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return UserProfile(user_id=user_id)
        data = json.loads(row["profile_json"])
        return UserProfile(
            user_id=user_id,
            preferences=data.get("preferences", []),
            working_style=data.get("working_style", ""),
            extra=data.get("extra", {}),
        )

    async def update(self, user_id: str, turn: Any) -> None:
        if self._conn is None:
            await self.connect()
        import datetime

        profile = await self.load(user_id)
        # Simple heuristic: record tool usage as preference signal
        tool_count = getattr(turn, "tool_call_count", 0)
        if tool_count >= 4 and "complex tasks" not in profile.preferences:
            profile.preferences.append("complex tasks")
        await self._conn.execute(
            "INSERT INTO user_profiles(user_id, profile_json, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
            "profile_json=excluded.profile_json, updated_at=excluded.updated_at",
            (
                user_id,
                json.dumps(
                    {
                        "preferences": profile.preferences,
                        "working_style": profile.working_style,
                        "extra": profile.extra,
                    }
                ),
                datetime.datetime.now(datetime.UTC).isoformat(),
            ),
        )
        await self._conn.commit()

    def render(self, profile: UserProfile) -> str:
        lines = ["[User model]"]
        for p in profile.preferences:
            lines.append(f"- {p}")
        if profile.working_style:
            lines.append(f"- {profile.working_style}")
        text = "\n".join(lines)
        if len(text) > MAX_RENDER_CHARS:
            text = text[:MAX_RENDER_CHARS]
        return text
