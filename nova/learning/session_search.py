"""FTS5-backed session search with LLM summarization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from nova.llm.provider import LLMProvider


@dataclass
class SearchHit:
    session_id: str
    snippet: str
    rank: float


class SessionSearch:
    """Incremental FTS5 index over session messages."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS session_fts "
            "USING fts5(session_id UNINDEXED, content, tokenize='unicode61')"
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def index_turn(self, session_id: str, messages: list[dict]) -> None:
        if self._conn is None:
            await self.connect()
        content = "\n".join(m.get("content", "") for m in messages if m.get("content"))
        if not content.strip():
            return
        await self._conn.execute(
            "INSERT INTO session_fts(session_id, content) VALUES (?, ?)",
            (session_id, content),
        )
        await self._conn.commit()

    async def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        if self._conn is None:
            await self.connect()
        if not query.strip():
            return []
        try:
            cursor = await self._conn.execute(
                "SELECT session_id, snippet(session_fts, 1, '', '', '...', 20) AS snip, "
                "bm25(session_fts) AS rnk FROM session_fts WHERE session_fts MATCH ? "
                "ORDER BY rnk LIMIT ?",
                (query, limit),
            )
            rows = await cursor.fetchall()
        except Exception:
            return []
        return [
            SearchHit(session_id=r["session_id"], snippet=r["snip"], rank=r["rnk"])
            for r in rows
        ]

    async def summarize(self, hits: list[SearchHit], query: str, llm: LLMProvider, model: str = "", session_id: str = "") -> str:
        if not hits:
            return "No matching sessions found."
        context = "\n\n".join(f"[{h.session_id}] {h.snippet}" for h in hits)
        prompt = (
            f"Summarize the following past session snippets relevant to: {query}\n\n"
            f"{context}\n\nProvide a concise summary."
        )
        try:
            chunks = []
            final = ""
            async for ev in llm.chat_stream(
                [{"role": "user", "content": prompt}], model=model or "gpt-4o", session_id=session_id, reasoning_effort="high"
            ):
                if type(ev).__name__ == "TextDelta" and getattr(ev, "content", None):
                    chunks.append(ev.content)
                if type(ev).__name__ == "Done":
                    final = getattr(ev, "content", "") or ""
                    break
                if type(ev).__name__ == "Error":
                    raise RuntimeError(getattr(ev, "message", "stream error"))
            return ("".join(chunks) or final) or context
        except Exception:
            return context
