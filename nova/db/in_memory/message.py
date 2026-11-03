"""Messages for the in-memory repository."""

from __future__ import annotations

import time
import uuid
from typing import Any

from nova.db.repository import MessageStore
from nova.session.models import Message, MessageFilter


class InMemoryMessageMixin(MessageStore):
    """Message access for ``InMemoryRepository``."""

    _messages: dict[str, Message]
    _sessions: dict[str, dict[str, Any]]

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
