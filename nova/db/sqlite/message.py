"""Messages for the sqlite repository."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import aiosqlite

from nova.db.repository import MessageStore
from nova.session.models import Message, MessageFilter, decode_display_text


def _legacy_content(data: str | None) -> str:
    """Content of a row written before messages had a `content` column.

    Older rows kept the text in `data`; newer ones use `data` for metadata such
    as the display text, which must not be mistaken for the message body.
    """
    if not data:
        return ""
    return "" if decode_display_text(data) is not None else data


def _parse_tool_calls(raw: str | None) -> list[dict[str, Any]] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _serialize_tool_calls(tool_calls: list[Any] | None) -> str | None:
    if not tool_calls:
        return None
    items: list[Any] = []
    for tool_call in tool_calls:
        if hasattr(tool_call, "model_dump"):
            items.append(tool_call.model_dump())
        elif isinstance(tool_call, dict):
            items.append(tool_call)
        else:
            items.append(str(tool_call))
    return json.dumps(items, ensure_ascii=False)


def _parse_provider_meta(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _row_to_message(row_dict: dict[str, Any]) -> Message:
    images_data = row_dict.get("images")
    images = json.loads(images_data) if images_data else None
    return Message(
        id=row_dict["id"],
        session_id=row_dict["session_id"],
        role=row_dict["role"],
        content=str(
            row_dict.get("content")
            if row_dict.get("content") is not None
            else _legacy_content(row_dict.get("data"))
        ),
        tool_calls=_parse_tool_calls(row_dict.get("tool_calls")),
        tool_call_id=row_dict.get("tool_call_id"),
        time_created=row_dict["time_created"],
        summary=row_dict.get("summary", 0),
        compacted=row_dict.get("compacted", 0),
        images=images,
        reasoning_content=row_dict.get("reasoning_content"),
        group_id=row_dict.get("group_id"),
        reasoning_elapsed_ms=row_dict.get("reasoning_elapsed_ms"),
        error=row_dict.get("error"),
        provider_meta=_parse_provider_meta(row_dict.get("provider_meta")),
        model=row_dict.get("model"),
        tokens_input=row_dict.get("tokens_input"),
        tokens_output=row_dict.get("tokens_output"),
        cache_read_tokens=row_dict.get("cache_read_tokens"),
        variant=row_dict.get("variant"),
        reasoning_effort=row_dict.get("reasoning_effort"),
        data=row_dict.get("data"),
    )


class SqliteMessageMixin(MessageStore):
    """Message access for ``SqliteRepository``."""

    _db: aiosqlite.Connection
    _lock: asyncio.Lock

    async def _ensure_connected(self) -> None:
        raise NotImplementedError

    async def _fetch_messages(
        self, sql: str, params: tuple[object, ...]
    ) -> list[Message]:
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_message(dict(row)) for row in rows]

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[Any] | None = None,
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
        await self._ensure_connected()
        msg_id = str(uuid.uuid4())
        now = int(time.time() * 1000)
        # A summary row describes the history it replaces, so it is stamped at
        # that position instead of at insertion time. That keeps the prompt in
        # chronological order and lets the next compaction fold the summary in
        # rather than keeping it alongside a freshly written one. The session's
        # updated_at deliberately stays at `now`, so sidebar ordering does not
        # move backwards.
        stamp = now if time_created is None else time_created

        images_json = json.dumps(images) if images else None
        provider_meta_json = (
            json.dumps(provider_meta, ensure_ascii=False) if provider_meta else None
        )

        async with self._lock:
            await self._db.execute(
                """INSERT INTO messages
                (id, session_id, role, content, data, tool_calls, tool_call_id, time_created, summary, images, reasoning_content, group_id, reasoning_elapsed_ms, tokens_input, tokens_output, cache_read_tokens, provider_meta, model, error, variant, reasoning_effort)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg_id,
                    session_id,
                    role,
                    content,
                    data,
                    _serialize_tool_calls(tool_calls),
                    tool_call_id,
                    stamp,
                    1 if summary else 0,
                    images_json,
                    reasoning_content,
                    group_id,
                    reasoning_elapsed_ms,
                    tokens_input,
                    tokens_output,
                    cache_read_tokens,
                    provider_meta_json,
                    model,
                    error,
                    variant,
                    reasoning_effort,
                ),
            )
            await self._db.execute(
                "UPDATE sessions SET updated_at = ?, message_count = message_count + 1 WHERE id = ?",
                (now, session_id),
            )
            await self._db.commit()

        return Message(
            id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            time_created=stamp,
            summary=1 if summary else 0,
            reasoning_content=reasoning_content,
            group_id=group_id,
            reasoning_elapsed_ms=reasoning_elapsed_ms,
            error=error,
            provider_meta=provider_meta,
            model=model,
            reasoning_effort=reasoning_effort,
            data=data,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cache_read_tokens=cache_read_tokens,
            variant=variant,
        )

    async def get_messages(
        self,
        session_id: str,
        msg_filter: MessageFilter | None = None,
    ) -> list[Message]:
        await self._ensure_connected()
        filter_value = msg_filter or MessageFilter()

        conditions = ["session_id = ?"]
        params: list[object] = [session_id]

        if not filter_value.include_compacted:
            conditions.append("compacted = 0")

        if filter_value.exclude_tool_role:
            conditions.append("role != 'tool'")

        if filter_value.only_non_summary:
            conditions.append("summary = 0")

        sql = f"SELECT * FROM messages WHERE {' AND '.join(conditions)} ORDER BY time_created ASC"
        if filter_value.limit is not None:
            sql += " LIMIT ?"
            params.append(filter_value.limit)

        return await self._fetch_messages(sql, tuple(params))

    async def compress_messages(self, session_id: str, target_count: int = 50) -> None:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            count = int(row[0]) if row else 0
            if count <= target_count:
                return

            delete_count = count - target_count
            await self._db.execute(
                """UPDATE messages SET summary = 1
                WHERE id IN (
                    SELECT id FROM messages
                    WHERE session_id = ? AND summary = 0
                    ORDER BY time_created ASC
                    LIMIT ?
                )""",
                (session_id, delete_count),
            )
            await self._db.execute(
                "UPDATE sessions SET compacted_at = ? WHERE id = ?",
                (int(time.time() * 1000), session_id),
            )
            await self._db.commit()

    async def mark_messages_compacted(self, session_id: str) -> None:
        await self._ensure_connected()
        async with self._lock:
            await self._db.execute(
                "UPDATE messages SET compacted = 1 WHERE session_id = ? AND compacted = 0 AND summary = 0",
                (session_id,),
            )
            await self._db.commit()

    async def mark_messages_compacted_by_ids(
        self, session_id: str, message_ids: list[str]
    ) -> None:
        await self._ensure_connected()
        if not message_ids:
            return
        placeholders = ",".join("?" * len(message_ids))
        async with self._lock:
            await self._db.execute(
                f"UPDATE messages SET compacted = 1 WHERE session_id = ? AND id IN ({placeholders})",
                (session_id, *message_ids),
            )
            await self._db.commit()

    async def update_message_content(self, message_id: str, content: str) -> None:
        await self._ensure_connected()
        async with self._lock:
            await self._db.execute(
                "UPDATE messages SET content = ?, data = ? WHERE id = ?",
                (content, content, message_id),
            )
            await self._db.commit()

    async def delete_messages(self, session_id: str, message_ids: list[str]) -> int:
        await self._ensure_connected()
        if not message_ids:
            return 0

        placeholders = ",".join("?" * len(message_ids))
        async with self._lock:
            count_cursor = await self._db.execute(
                f"SELECT COUNT(*) FROM messages WHERE session_id = ? AND id IN ({placeholders})",
                (session_id, *message_ids),
            )
            row = await count_cursor.fetchone()
            deleted_count = int(row[0]) if row and row[0] else 0
            if deleted_count == 0:
                return 0

            await self._db.execute(
                f"DELETE FROM messages WHERE session_id = ? AND id IN ({placeholders})",
                (session_id, *message_ids),
            )
            await self._db.execute(
                """UPDATE sessions
                SET updated_at = ?,
                    message_count = CASE
                        WHEN message_count >= ? THEN message_count - ?
                        ELSE 0
                    END
                WHERE id = ?""",
                (int(time.time() * 1000), deleted_count, deleted_count, session_id),
            )
            await self._db.commit()
            return deleted_count
