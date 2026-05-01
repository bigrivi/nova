from nova.db.database import Message
from nova.session.history_projection import (
    VISIBLE_HISTORY_TOOL_NAMES,
    build_user_visible_history_filter,
    project_user_visible_history,
)


def _message(
    *,
    message_id: str,
    role: str,
    content: str,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
    summary: int = 0,
) -> Message:
    return Message(
        id=message_id,
        session_id="sess-1",
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        summary=summary,
    )


def test_build_user_visible_history_filter_matches_session_history_needs():
    msg_filter = build_user_visible_history_filter()

    assert msg_filter.include_compacted is True
    assert msg_filter.only_non_summary is True
    assert msg_filter.exclude_tool_role is False


def test_project_user_visible_history_keeps_only_visible_tool_calls_and_results():
    messages = [
        _message(message_id="m1", role="user", content="hello"),
        _message(
            message_id="m2",
            role="assistant",
            content="",
            tool_calls=[
                {"id": "call_bash", "name": "bash", "arguments": "{\"command\":\"pwd\"}"},
                {"id": "call_edit", "name": "edit", "arguments": "{\"filePath\":\"foo.py\"}"},
            ],
        ),
        _message(message_id="m3", role="tool", content="/tmp", tool_call_id="call_bash"),
        _message(
            message_id="m4",
            role="tool",
            content="Changes applied to foo.py:\n\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n",
            tool_call_id="call_edit",
        ),
        _message(
            message_id="m5",
            role="assistant",
            content="[Previous conversation summary]\nsummary text",
            summary=1,
        ),
        _message(
            message_id="m6",
            role="tool",
            content="prefix\n[... 42 chars snipped ...]\nsuffix",
            tool_call_id="call_edit",
        ),
    ]

    projected = project_user_visible_history(messages)

    assert [message.id for message in projected] == ["m1", "m2", "m4"]
    assert projected[1].tool_calls == [
        {"id": "call_edit", "name": "edit", "arguments": "{\"filePath\":\"foo.py\"}"}
    ]
    assert projected[2].tool_call_id == "call_edit"
    assert all("summary" not in message.content for message in projected)
    assert all("/tmp" not in message.content for message in projected)


def test_project_user_visible_history_visible_tool_allowlist_is_intentional():
    assert VISIBLE_HISTORY_TOOL_NAMES == {"ask_user", "edit", "write"}
