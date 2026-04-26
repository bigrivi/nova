"""Server-side request, response, and streaming event schemas."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    provider: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    request_id: str
    session_id: str | None = None
    status: Literal["completed", "cancelled", "input_required", "error"]
    message: str = ""


class SessionSummary(BaseModel):
    id: str
    title: str | None = None
    updated_at: int


class SessionListResponse(BaseModel):
    items: list[SessionSummary]


class MessageRecord(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    time_created: int


class MessageListResponse(BaseModel):
    items: list[MessageRecord]


class InterruptResponse(BaseModel):
    request_id: str
    interrupted: bool


class BaseStreamEventData(BaseModel):
    request_id: str
    session_id: str | None = None
    sequence: int


class SessionStartedEventData(BaseStreamEventData):
    pass


class ResponseStartedEventData(BaseStreamEventData):
    pass


class MessageDeltaEventData(BaseStreamEventData):
    delta: str


class ToolCallEventData(BaseStreamEventData):
    tool_name: str
    tool_call_id: str
    arguments: str


class ToolResultEventData(BaseStreamEventData):
    tool_name: str
    tool_call_id: str
    success: bool
    content: str
    error: str
    requires_input: bool


class ResponseCompletedEventData(BaseStreamEventData):
    content: str


class ResponseCancelledEventData(BaseStreamEventData):
    message: str


class InputRequiredEventData(BaseStreamEventData):
    message: str


class ResponseErrorEventData(BaseStreamEventData):
    message: str


class StreamEvent(BaseModel):
    type: str
    data: BaseStreamEventData


class SessionStartedEvent(StreamEvent):
    type: Literal["session.started"] = "session.started"
    data: SessionStartedEventData


class ResponseStartedEvent(StreamEvent):
    type: Literal["response.started"] = "response.started"
    data: ResponseStartedEventData


class MessageDeltaEvent(StreamEvent):
    type: Literal["message.delta"] = "message.delta"
    data: MessageDeltaEventData


class ToolCallEvent(StreamEvent):
    type: Literal["tool.call"] = "tool.call"
    data: ToolCallEventData


class ToolResultEvent(StreamEvent):
    type: Literal["tool.result"] = "tool.result"
    data: ToolResultEventData


class ResponseCompletedEvent(StreamEvent):
    type: Literal["response.completed"] = "response.completed"
    data: ResponseCompletedEventData


class ResponseCancelledEvent(StreamEvent):
    type: Literal["response.cancelled"] = "response.cancelled"
    data: ResponseCancelledEventData


class InputRequiredEvent(StreamEvent):
    type: Literal["input.required"] = "input.required"
    data: InputRequiredEventData


class ResponseErrorEvent(StreamEvent):
    type: Literal["response.error"] = "response.error"
    data: ResponseErrorEventData


ServerStreamEvent: TypeAlias = (
    SessionStartedEvent
    | ResponseStartedEvent
    | MessageDeltaEvent
    | ToolCallEvent
    | ToolResultEvent
    | ResponseCompletedEvent
    | ResponseCancelledEvent
    | InputRequiredEvent
    | ResponseErrorEvent
)


def stream_event_data_to_dict(data: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(data, BaseModel):
        return data.model_dump()
    return data
