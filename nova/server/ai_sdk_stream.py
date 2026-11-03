"""
AI SDK UI stream protocol adapter for assistant-ui compatible SSE responses.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from nova.agent import AgentEvent

log = logging.getLogger(__name__)


def encode_ai_sdk_sse(part: dict[str, Any]) -> bytes:
    payload = json.dumps(part, ensure_ascii=False, separators=(",", ":"))
    return f"data: {payload}\n\n".encode()


def encode_ai_sdk_done() -> bytes:
    return b"data: [DONE]\n\n"


#: Shown on a tool call whose result never arrived. Deliberately a statement
#: about the turn, not a guess at why: the adapter cannot know.
UNANSWERED_TOOL_MESSAGE = "Tool call did not finish: the turn ended before it returned."


def _parse_done_payload(payload: object) -> tuple[str, str]:
    if isinstance(payload, dict):
        reason = payload.get("reason")
        content = payload.get("content")
        return (
            reason if isinstance(reason, str) else "",
            content if isinstance(content, str) else "",
        )
    if isinstance(payload, str):
        return "", payload
    return "", ""


def _parse_tool_input(arguments: object) -> object:
    if isinstance(arguments, (dict, list)):
        return arguments
    if not isinstance(arguments, str):
        return {}
    text = arguments.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": arguments}


def _parse_tool_output(result: object) -> object:
    content = getattr(result, "content", "")
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return {"value": content}
    text = content.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"content": content}


class AISDKStreamAdapter:
    """Turn agent events into AI SDK UI SSE frames.

    Args:
        wake_variant: Set when the server injected this turn's user message
            rather than the user sending it (a sub-agent completion). The
            message is persisted with this variant, but nothing in the AI SDK
            protocol carries a user message, so a client that attaches to the
            live turn would show a bare reply with nothing above it. The frame
            emitted here is what lets the renderer put the chip back.
        wake_text: The injected user message, verbatim.
    """

    def __init__(self, wake_variant: str | None = None, wake_text: str = "") -> None:
        self._message_started = False
        self._step_started = False
        self._active_text_id: str | None = None
        self._active_reasoning_id: str | None = None
        self._message_id = f"msg_{uuid.uuid4().hex}"
        self._text_emitted = False
        self._wake_variant = wake_variant
        self._wake_text = wake_text
        self._wake_sent = False
        # Announced tool calls awaiting their result, by id. Every terminal
        # frame must leave this empty: a client draws an unanswered call as
        # still running forever, and a turn that stops here leaves it nothing
        # to cancel.
        self._open_tool_calls: dict[str, str] = {}

    def _wake_frame(self) -> list[bytes]:
        """The injected-message frame, emitted at most once per turn.

        A turn can run several steps (a tool call resumes the loop), so the
        latch keeps a later TURN_START from repeating a message the client has
        already inserted.
        """
        if self._wake_sent or not self._wake_variant or not self._wake_text:
            return []
        self._wake_sent = True
        return [
            encode_ai_sdk_sse(
                {
                    "type": "data-nova-wake",
                    "data": {
                        "variant": self._wake_variant,
                        "text": self._wake_text,
                        "messageId": self._message_id,
                    },
                }
            )
        ]

    def _close_open_parts(self) -> list[bytes]:
        chunks: list[bytes] = []
        # An announced call with no result keeps a client's tool block spinning
        # in a turn whose stream is already over -- the failure is invisible and
        # uncancellable at that point. Whatever the reason the result never came
        # (a dropped malformed call, a refusal path that ends the turn, a bug in
        # a tool invoker), the wire owes the client an answer before it closes.
        for tool_call_id, tool_name in self._open_tool_calls.items():
            # The wire is repaired here, but a result that never arrived is a
            # bug upstream; say so, because the frame alone is indistinguishable
            # from a legitimately failed tool.
            log.warning(
                "Turn ended with an unanswered tool call: %s (%s)",
                tool_name,
                tool_call_id,
            )
            chunks.append(
                encode_ai_sdk_sse(
                    {
                        "type": "data-nova-tool-error",
                        "data": {
                            "toolName": tool_name,
                            "toolCallId": tool_call_id,
                            "message": UNANSWERED_TOOL_MESSAGE,
                        },
                    }
                )
            )
        self._open_tool_calls.clear()
        if self._step_started:
            chunks.append(encode_ai_sdk_sse({"type": "finish-step"}))
            self._step_started = False
        return chunks

    def feed(self, event: AgentEvent, data: object) -> list[bytes]:
        handler = _HANDLERS.get(event)
        return handler(self, data) if handler is not None else []

    def _on_session(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        session_id = data if isinstance(data, str) else ""
        if session_id:
            chunks.append(
                encode_ai_sdk_sse(
                    {
                        "type": "data-nova-session",
                        "data": {"sessionId": session_id},
                    }
                )
            )
        return chunks

    def _on_start(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        return chunks

    def _on_turn_start(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        if not self._message_started:
            # Before the assistant's own start frame, so the client can
            # place the injected message above the reply it introduces.
            chunks.extend(self._wake_frame())
            chunks.append(
                encode_ai_sdk_sse(
                    {
                        "type": "start",
                        "messageId": self._message_id,
                    }
                )
            )
            self._message_started = True
        chunks.append(encode_ai_sdk_sse({"type": "start-step"}))
        self._step_started = True
        return chunks

    def _on_turn_end(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        chunks.extend(self._close_open_parts())
        return chunks

    def _on_text_start(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        self._active_text_id = f"text_{uuid.uuid4().hex}"
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "text-start",
                    "id": self._active_text_id,
                }
            )
        )
        return chunks

    def _on_text_end(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        if self._active_text_id is not None:
            chunks.append(
                encode_ai_sdk_sse(
                    {
                        "type": "text-end",
                        "id": self._active_text_id,
                    }
                )
            )
            self._active_text_id = None
        return chunks

    def _on_text_delta(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "text-delta",
                    "id": self._active_text_id,
                    "delta": data if isinstance(data, str) else str(data),
                }
            )
        )
        self._text_emitted = True
        return chunks

    def _on_reasoning_start(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        self._active_reasoning_id = f"reasoning_{uuid.uuid4().hex}"
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "reasoning-start",
                    "id": self._active_reasoning_id,
                }
            )
        )
        return chunks

    def _on_reasoning_delta(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        if self._active_reasoning_id is not None:
            chunks.append(
                encode_ai_sdk_sse(
                    {
                        "type": "reasoning-delta",
                        "id": self._active_reasoning_id,
                        "delta": data if isinstance(data, str) else str(data),
                    }
                )
            )
        return chunks

    def _on_reasoning_end(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        if self._active_reasoning_id is not None:
            chunk_data: dict[str, Any] = {
                "type": "reasoning-end",
                "id": self._active_reasoning_id,
            }
            if data is not None:
                chunk_data["elapsedMs"] = data
            chunks.append(encode_ai_sdk_sse(chunk_data))
            self._active_reasoning_id = None
        return chunks

    def _on_tool_call(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        tool_name = getattr(data, "name", str(data))
        tool_call_id = getattr(data, "id", "") or f"tool_{uuid.uuid4().hex}"
        tool_input = _parse_tool_input(getattr(data, "arguments", ""))
        self._open_tool_calls[tool_call_id] = tool_name
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "tool-input-start",
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                }
            )
        )
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "tool-input-available",
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "input": tool_input,
                }
            )
        )
        return chunks

    def _on_tool_result(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        assert isinstance(data, dict)
        result = data["result"]
        tool_call_id = data.get("tool_call_id", "")
        tool_name = data["tool"]
        self._open_tool_calls.pop(tool_call_id, None)
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "tool-output-available",
                    "toolCallId": tool_call_id,
                    "output": _parse_tool_output(result),
                }
            )
        )
        if not getattr(result, "success", False):
            chunks.append(
                encode_ai_sdk_sse(
                    {
                        "type": "data-nova-tool-error",
                        "data": {
                            "toolName": tool_name,
                            "toolCallId": tool_call_id,
                            "message": getattr(result, "content", "")
                            or getattr(result, "error", ""),
                        },
                    }
                )
            )
        return chunks

    def _on_approval_heartbeat(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        chunks.append(b'data: {"type":"data-nova-heartbeat"}\n\n')
        return chunks

    def _on_approval_result(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        data_payload = data if isinstance(data, dict) else {}
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "data-nova-approval-resolved",
                    "data": {
                        "requestId": data_payload.get("id", ""),
                        "approved": bool(data_payload.get("approved", False)),
                    },
                }
            )
        )
        return chunks

    def _on_approval_required(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        data_payload = data if isinstance(data, dict) else {}
        # The boundary the tool axis judged the path against, read the same way
        # `chat_stream` reads it for the other serializer. The payload does not
        # carry it, and a frame that always sent an empty string would tell the
        # dialog there is no workspace on a turn deciding every path against one.
        from nova.tools.workspace_context import get_active_workspace

        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "data-nova-approval-required",
                    "data": {
                        "sessionId": data_payload.get("sessionId", ""),
                        "requestId": data_payload.get("id", ""),
                        "command": data_payload.get("command", ""),
                        "description": data_payload.get("description", ""),
                        "toolCallId": data_payload.get("toolCallId", ""),
                        "toolName": data_payload.get("toolName", ""),
                        "rememberable": data_payload.get("rememberable", True),
                        "family": data_payload.get("family", ""),
                        "target": data_payload.get("target", ""),
                        "scriptScoped": bool(data_payload.get("digest", "")),
                        "dangerous": data_payload.get("dangerous", False),
                        "workspace": get_active_workspace() or "",
                    },
                }
            )
        )
        return chunks

    def _on_compaction_start(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        data_payload = data if isinstance(data, dict) else {}
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "data-nova-compaction-start",
                    "data": {
                        "message_count": data_payload.get("message_count", 0),
                        "token_count": data_payload.get("token_count", 0),
                        "reason": data_payload.get("reason", "threshold"),
                    },
                }
            )
        )
        return chunks

    def _on_compaction_delta(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        data_payload = data if isinstance(data, dict) else {}
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "data-nova-compaction-delta",
                    "data": {"delta": data_payload.get("delta", "")},
                }
            )
        )
        return chunks

    def _on_compaction_end(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "data-nova-compaction-end",
                }
            )
        )
        return chunks

    def _on_context_update(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        payload = data if isinstance(data, dict) else {}
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "data-nova-context",
                    "data": {
                        "used": int(payload.get("used", 0)),
                        "limit": int(payload.get("limit", 0)),
                        "percent": int(payload.get("percent", 0)),
                    },
                }
            )
        )
        return chunks

    def _on_retry(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        payload = data if isinstance(data, dict) else {}
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "data-nova-retry",
                    "data": {
                        "attempt": int(payload.get("attempt", 0)),
                        "total": int(payload.get("total", 0)),
                        "wait_seconds": float(payload.get("wait_seconds", 0.0)),
                        "reason": str(payload.get("reason", "")),
                    },
                }
            )
        )
        return chunks

    def _on_done(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        reason, content = _parse_done_payload(data)
        chunks.extend(self._close_open_parts())
        if reason == "stopped":
            chunks.append(encode_ai_sdk_sse({"type": "abort"}))
        elif reason == "tool_failed":
            chunks.append(
                encode_ai_sdk_sse(
                    {
                        "type": "error",
                        "errorText": content or "Tool execution failed",
                    }
                )
            )
        elif reason == "requires_input":
            chunks.append(
                encode_ai_sdk_sse(
                    {
                        "type": "data-nova-input-required",
                        "data": {"message": content or "User input required"},
                    }
                )
            )
        elif content and not self._text_emitted:
            text_id = f"text_{uuid.uuid4().hex}"
            if not self._message_started:
                chunks.append(
                    encode_ai_sdk_sse({"type": "start", "messageId": self._message_id})
                )
                self._message_started = True
            chunks.extend(
                [
                    encode_ai_sdk_sse({"type": "text-start", "id": text_id}),
                    encode_ai_sdk_sse(
                        {"type": "text-delta", "id": text_id, "delta": content}
                    ),
                    encode_ai_sdk_sse({"type": "text-end", "id": text_id}),
                ]
            )
            self._text_emitted = True
        chunks.append(encode_ai_sdk_sse({"type": "finish"}))
        chunks.append(encode_ai_sdk_done())
        return chunks

    def _on_error(self, data: object) -> list[bytes]:
        chunks: list[bytes] = []
        chunks.extend(self._close_open_parts())
        message = ""
        if isinstance(data, dict):
            message = data.get("message", "") or ""
        elif isinstance(data, str):
            message = data
        chunks.append(
            encode_ai_sdk_sse(
                {
                    "type": "error",
                    "errorText": message or "Unknown error",
                }
            )
        )
        chunks.append(encode_ai_sdk_done())
        return chunks


_HANDLERS: dict[AgentEvent, Callable[[AISDKStreamAdapter, object], list[bytes]]] = {
    AgentEvent.SESSION: AISDKStreamAdapter._on_session,
    AgentEvent.START: AISDKStreamAdapter._on_start,
    AgentEvent.TURN_START: AISDKStreamAdapter._on_turn_start,
    AgentEvent.TURN_END: AISDKStreamAdapter._on_turn_end,
    AgentEvent.TEXT_START: AISDKStreamAdapter._on_text_start,
    AgentEvent.TEXT_END: AISDKStreamAdapter._on_text_end,
    AgentEvent.TEXT_DELTA: AISDKStreamAdapter._on_text_delta,
    AgentEvent.REASONING_START: AISDKStreamAdapter._on_reasoning_start,
    AgentEvent.REASONING_DELTA: AISDKStreamAdapter._on_reasoning_delta,
    AgentEvent.REASONING_END: AISDKStreamAdapter._on_reasoning_end,
    AgentEvent.TOOL_CALL: AISDKStreamAdapter._on_tool_call,
    AgentEvent.TOOL_RESULT: AISDKStreamAdapter._on_tool_result,
    AgentEvent.APPROVAL_HEARTBEAT: AISDKStreamAdapter._on_approval_heartbeat,
    AgentEvent.APPROVAL_RESULT: AISDKStreamAdapter._on_approval_result,
    AgentEvent.APPROVAL_REQUIRED: AISDKStreamAdapter._on_approval_required,
    AgentEvent.COMPACTION_START: AISDKStreamAdapter._on_compaction_start,
    AgentEvent.COMPACTION_DELTA: AISDKStreamAdapter._on_compaction_delta,
    AgentEvent.COMPACTION_END: AISDKStreamAdapter._on_compaction_end,
    AgentEvent.CONTEXT_UPDATE: AISDKStreamAdapter._on_context_update,
    AgentEvent.RETRY: AISDKStreamAdapter._on_retry,
    AgentEvent.DONE: AISDKStreamAdapter._on_done,
    AgentEvent.ERROR: AISDKStreamAdapter._on_error,
}
