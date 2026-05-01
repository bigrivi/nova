from __future__ import annotations

from dataclasses import replace

from nova.db.database import Database, Message, MessageFilter


VISIBLE_HISTORY_TOOL_NAMES = frozenset({"ask_user", "edit", "write"})
_SNIPPED_TOOL_RESULT_MARKER = " chars snipped ...]"


def build_user_visible_history_filter() -> MessageFilter:
    return MessageFilter(
        include_compacted=True,
        only_non_summary=True,
    )


async def get_user_visible_history(
    db: Database,
    session_id: str,
) -> list[Message]:
    messages = await db.get_messages(
        session_id,
        build_user_visible_history_filter(),
    )
    return project_user_visible_history(messages)


def project_user_visible_history(messages: list[Message]) -> list[Message]:
    visible_tool_call_ids = {
        tool_call_id
        for message in messages
        if message.role == "assistant"
        for tool_call in (message.tool_calls or [])
        if _is_visible_tool_call(tool_call)
        for tool_call_id in [_tool_call_id(tool_call)]
        if tool_call_id
    }

    projected: list[Message] = []

    for message in messages:
        if _is_summary_message(message):
            continue

        if message.role == "assistant":
            visible_tool_calls = [
                tool_call
                for tool_call in (message.tool_calls or [])
                if _is_visible_tool_call(tool_call)
            ]
            next_message = replace(
                message,
                tool_calls=visible_tool_calls or None,
            )
            if _has_visible_assistant_payload(next_message):
                projected.append(next_message)
            continue

        if message.role == "tool":
            if (
                _is_snipped_tool_message(message)
                or not _is_visible_tool_result(message, visible_tool_call_ids)
            ):
                continue
            projected.append(message)
            continue

        projected.append(message)

    return projected


def _has_visible_assistant_payload(message: Message) -> bool:
    return bool((message.content or "").strip() or message.tool_calls)


def _is_visible_tool_call(tool_call: object) -> bool:
    return _tool_call_name(tool_call) in VISIBLE_HISTORY_TOOL_NAMES


def _is_visible_tool_result(message: Message, visible_tool_call_ids: set[str]) -> bool:
    tool_call_id = (message.tool_call_id or "").strip()
    return bool(tool_call_id and tool_call_id in visible_tool_call_ids)


def _is_summary_message(message: Message) -> bool:
    return bool(message.summary == 1)


def _is_snipped_tool_message(message: Message) -> bool:
    return (
        message.role == "tool"
        and "[... " in message.content
        and _SNIPPED_TOOL_RESULT_MARKER in message.content
    )


def _tool_call_id(tool_call: object) -> str:
    if isinstance(tool_call, dict):
        value = tool_call.get("id")
    else:
        value = getattr(tool_call, "id", None)
    return value.strip() if isinstance(value, str) else ""


def _tool_call_name(tool_call: object) -> str:
    if isinstance(tool_call, dict):
        value = tool_call.get("name")
    else:
        value = getattr(tool_call, "name", None)
    return value.strip().lower() if isinstance(value, str) else ""
