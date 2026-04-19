"""
Chat service that maps internal agent events to stable backend events.
"""

from __future__ import annotations

import uuid
from typing import Any, AsyncGenerator, Callable

from nova.agent import AgentEvent
from nova.app import build_agent
from nova.db.database import ensure_db
from nova.server.request_registry import RequestRegistry
from nova.server.schemas import (
    BaseStreamEventData,
    ChatRequest,
    ChatResponse,
    InputRequiredEvent,
    InputRequiredEventData,
    MessageDeltaEvent,
    MessageDeltaEventData,
    MessageListResponse,
    MessageRecord,
    ResponseCancelledEvent,
    ResponseCancelledEventData,
    ResponseCompletedEvent,
    ResponseCompletedEventData,
    ResponseErrorEvent,
    ResponseErrorEventData,
    ResponseStartedEvent,
    ResponseStartedEventData,
    ServerStreamEvent,
    SessionListResponse,
    SessionStartedEvent,
    SessionStartedEventData,
    SessionSummary,
    ToolCallEvent,
    ToolCallEventData,
    ToolResultEvent,
    ToolResultEventData,
    stream_event_data_to_dict,
)
from nova.settings import Settings


class ChatService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._request_registry = RequestRegistry()

    async def list_sessions(self) -> SessionListResponse:
        db = await ensure_db()
        sessions = await db.get_all_sessions()
        items = [
            SessionSummary(
                id=session["id"],
                title=session.get("title"),
                status=session.get("status", "active"),
                updated_at=session.get("updated_at", 0),
            )
            for session in sessions
        ]
        return SessionListResponse(items=items)

    async def list_messages(self, session_id: str) -> MessageListResponse:
        db = await ensure_db()
        messages = await db.get_history_messages(session_id)
        items = [
            MessageRecord(
                id=message.id,
                session_id=message.session_id,
                role=message.role,
                content=message.content,
                tool_call_id=message.tool_call_id,
                tool_calls=message.tool_calls or [],
                time_created=message.time_created,
            )
            for message in messages
        ]
        return MessageListResponse(items=items)

    async def interrupt(self, request_id: str) -> bool:
        return await self._request_registry.interrupt(request_id)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        response: ChatResponse | None = None
        async for event in self.chat_stream(request):
            payload = stream_event_data_to_dict(event.data)
            if event.type == "response.completed":
                response = ChatResponse(
                    request_id=payload["request_id"],
                    session_id=payload.get("session_id"),
                    status="completed",
                    message=payload.get("content", ""),
                )
            elif event.type == "response.cancelled":
                response = ChatResponse(
                    request_id=payload["request_id"],
                    session_id=payload.get("session_id"),
                    status="cancelled",
                    message=payload.get("message", ""),
                )
            elif event.type == "input.required":
                response = ChatResponse(
                    request_id=payload["request_id"],
                    session_id=payload.get("session_id"),
                    status="input_required",
                    message=payload.get("message", ""),
                )
            elif event.type == "response.error":
                response = ChatResponse(
                    request_id=payload["request_id"],
                    session_id=payload.get("session_id"),
                    status="error",
                    message=payload.get("message", ""),
                )
        if response is None:
            raise RuntimeError("Chat finished without a terminal event.")
        return response

    async def chat_stream(self, request: ChatRequest) -> AsyncGenerator[ServerStreamEvent, None]:
        request_id = f"req_{uuid.uuid4().hex}"
        runtime_settings = self._settings
        if request.provider is not None or request.model is not None:
            from dataclasses import replace

            runtime_settings = replace(
                self._settings,
                provider=self._settings.provider if request.provider is None else request.provider,
                model=self._settings.model if request.model is None else request.model,
            )
        agent = build_agent(settings=runtime_settings)
        session_id = request.session_id
        sequence = 0

        async def emit(
            event_cls: type,
            data_cls: type[BaseStreamEventData],
            **payload: Any,
        ) -> ServerStreamEvent:
            nonlocal sequence, session_id
            sequence += 1
            event_session_id = payload.get("session_id") or session_id
            if event_session_id:
                session_id = event_session_id
            data_payload = {
                **payload,
                "request_id": request_id,
                "session_id": session_id,
                "sequence": sequence,
            }
            return event_cls(
                data=data_cls(
                    **data_payload,
                )
            )

        await self._request_registry.register(request_id, agent)
        try:
            async for event, data in agent.chat_stream(
                request.message,
                session_id=request.session_id,
            ):
                mapped = await self._map_agent_event(
                    agent_event=event,
                    data=data,
                    emit=emit,
                )
                if mapped is None:
                    continue
                yield mapped
        except Exception as exc:
            yield await emit(ResponseErrorEvent, ResponseErrorEventData, message=str(exc))
        finally:
            await self._request_registry.unregister(request_id)

    async def _map_agent_event(
        self,
        agent_event: AgentEvent,
        data: Any,
        emit: Callable[..., Any],
    ) -> ServerStreamEvent | None:
        if agent_event == AgentEvent.SESSION:
            return await emit(SessionStartedEvent, SessionStartedEventData, session_id=data)
        if agent_event == AgentEvent.LLM_START:
            return await emit(ResponseStartedEvent, ResponseStartedEventData)
        if agent_event == AgentEvent.TEXT_DELTA:
            return await emit(MessageDeltaEvent, MessageDeltaEventData, delta=data)
        if agent_event == AgentEvent.TOOL_CALL:
            arguments = getattr(data, "arguments", "")
            return await emit(
                ToolCallEvent,
                ToolCallEventData,
                tool_name=getattr(data, "name", str(data)),
                tool_call_id=getattr(data, "id", ""),
                arguments=arguments,
            )
        if agent_event == AgentEvent.TOOL_RESULT:
            result = data["result"]
            return await emit(
                ToolResultEvent,
                ToolResultEventData,
                tool_name=data["tool"],
                tool_call_id=data.get("tool_call_id", ""),
                success=result.success,
                content=result.content,
                error=result.error or "",
                requires_input=result.requires_input,
            )
        if agent_event == AgentEvent.DONE:
            if data == "Stopped by user":
                return await emit(
                    ResponseCancelledEvent,
                    ResponseCancelledEventData,
                    message=data,
                )
            if data == "User input required":
                return await emit(
                    InputRequiredEvent,
                    InputRequiredEventData,
                    message=data,
                )
            return await emit(
                ResponseCompletedEvent,
                ResponseCompletedEventData,
                content=data or "",
            )
        if agent_event == AgentEvent.ERROR:
            return await emit(
                ResponseErrorEvent,
                ResponseErrorEventData,
                message=str(data),
            )
        return None
