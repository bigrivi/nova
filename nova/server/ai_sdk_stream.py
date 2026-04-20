"""
AI SDK UI stream protocol adapter for assistant-ui compatible SSE responses.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from nova.agent import AgentEvent


def encode_ai_sdk_sse(part: dict[str, Any]) -> bytes:
    payload = json.dumps(part, ensure_ascii=False, separators=(",", ":"))
    return f"data: {payload}\n\n".encode("utf-8")


def encode_ai_sdk_done() -> bytes:
    return b"data: [DONE]\n\n"


def _parse_done_payload(payload: Any) -> tuple[str, str]:
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


def _parse_tool_input(arguments: Any) -> Any:
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


def _parse_tool_output(result: Any) -> Any:
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
    def __init__(self) -> None:
        self._message_started = False
        self._step_started = False
        self._active_text_id: str | None = None
        self._message_id = f"msg_{uuid.uuid4().hex}"
        self._text_emitted = False

    def _close_open_parts(self) -> list[bytes]:
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
        if self._step_started:
            chunks.append(encode_ai_sdk_sse({"type": "finish-step"}))
            self._step_started = False
        return chunks

    def feed(self, event: AgentEvent, data: Any) -> list[bytes]:
        chunks: list[bytes] = []

        if event == AgentEvent.SESSION:
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

        if event == AgentEvent.LLM_START:
            if not self._message_started:
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

        if event == AgentEvent.TEXT_DELTA:
            if self._active_text_id is None:
                self._active_text_id = f"text_{uuid.uuid4().hex}"
                chunks.append(
                    encode_ai_sdk_sse(
                        {
                            "type": "text-start",
                            "id": self._active_text_id,
                        }
                    )
                )
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

        if event == AgentEvent.LLM_END:
            chunks.extend(self._close_open_parts())
            return chunks

        if event == AgentEvent.TOOL_CALL:
            tool_name = getattr(data, "name", str(data))
            tool_call_id = getattr(data, "id", "") or f"tool_{uuid.uuid4().hex}"
            tool_input = _parse_tool_input(getattr(data, "arguments", ""))
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

        if event == AgentEvent.TOOL_RESULT:
            result = data["result"]
            tool_call_id = data.get("tool_call_id", "")
            tool_name = data["tool"]
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
                                "message": getattr(result, "content", "") or getattr(result, "error", ""),
                            },
                        }
                    )
                )
            return chunks

        if event == AgentEvent.DONE:
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
                    chunks.append(encode_ai_sdk_sse({"type": "start", "messageId": self._message_id}))
                    self._message_started = True
                chunks.extend(
                    [
                        encode_ai_sdk_sse({"type": "text-start", "id": text_id}),
                        encode_ai_sdk_sse({"type": "text-delta", "id": text_id, "delta": content}),
                        encode_ai_sdk_sse({"type": "text-end", "id": text_id}),
                    ]
                )
                self._text_emitted = True
            chunks.append(encode_ai_sdk_sse({"type": "finish"}))
            chunks.append(encode_ai_sdk_done())
            return chunks

        if event == AgentEvent.ERROR:
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

        return chunks
