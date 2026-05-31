"""
Chat service that maps internal agent events to stable backend events.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Callable

from nova.agent import AgentEvent
from nova.app import build_agent
from nova.constants import DEFAULT_AGENT_KEY
from nova.db.database import ensure_db
from nova.server.ai_sdk_stream import AISDKStreamAdapter
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
from nova.session.history_projection import get_user_visible_history
from nova.settings import Settings


class ChatService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._request_registry = RequestRegistry()

    async def list_sessions(self, agent_key: str | None = None) -> SessionListResponse:
        db = await ensure_db()
        sessions = await db.get_all_sessions(agent_key=agent_key)
        items = [
            SessionSummary(
                id=session["id"],
                title=session.get("title"),
                updated_at=session.get("updated_at", 0),
                agent_key=session.get("agent_key", DEFAULT_AGENT_KEY),
            )
            for session in sessions
        ]
        return SessionListResponse(items=items)

    async def list_messages(self, session_id: str) -> MessageListResponse:
        db = await ensure_db()
        messages = await get_user_visible_history(db, session_id)
        items = [
            MessageRecord(
                id=message.id,
                session_id=message.session_id,
                role=message.role,
                content=message.content,
                tool_call_id=message.tool_call_id,
                tool_calls=message.tool_calls or [],
                time_created=message.time_created,
                images=message.images,
                reasoning_content=message.reasoning_content,
                group_id=message.group_id,
            )
            for message in messages
        ]
        return MessageListResponse(items=items)

    async def interrupt(self, session_id: str) -> bool:
        return await self._request_registry.interrupt(session_id)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        response: ChatResponse | None = None
        async for event in self.chat_stream(request):
            payload = stream_event_data_to_dict(event.data)
            if event.type == "response.completed":
                response = ChatResponse(
                    session_id=payload.get("session_id"),
                    status="completed",
                    message=payload.get("content", ""),
                )
            elif event.type == "response.cancelled":
                response = ChatResponse(
                    session_id=payload.get("session_id"),
                    status="cancelled",
                    message=payload.get("message", ""),
                )
            elif event.type == "input.required":
                response = ChatResponse(
                    session_id=payload.get("session_id"),
                    status="input_required",
                    message=payload.get("message", ""),
                )
            elif event.type == "response.error":
                response = ChatResponse(
                    session_id=payload.get("session_id"),
                    status="error",
                    message=payload.get("message", ""),
                )
        if response is None:
            raise RuntimeError("Chat finished without a terminal event.")
        return response

    async def chat_stream(self, request: ChatRequest) -> AsyncGenerator[ServerStreamEvent, None]:
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
                "session_id": session_id,
                "sequence": sequence,
            }
            return event_cls(
                data=data_cls(
                    **data_payload,
                )
            )

        try:
            async for event, data in self._agent_event_stream(request):
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

    async def chat_stream_ai_sdk(self, request: ChatRequest) -> AsyncGenerator[bytes, None]:
        adapter = AISDKStreamAdapter()
        async for event, data in self._agent_event_stream(request):
            for chunk in adapter.feed(event, data):
                yield chunk

    async def _agent_event_stream(
        self,
        request: ChatRequest,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        agent = await build_agent(
            agent_key=request.agent_key,
            provider=request.provider,
            model=request.model,
        )
        register_key = request.session_id
        if register_key:
            await self._request_registry.register(register_key, agent)
        attachment_dicts = [att.model_dump() for att in request.attachments]
        try:
            async for event, data in agent.chat_stream(
                request.message,
                session_id=request.session_id,
                attachments=attachment_dicts,
            ):
                if event == AgentEvent.SESSION and data and not register_key:
                    register_key = data
                    await self._request_registry.register(register_key, agent)
                yield event, data
        finally:
            if register_key:
                await self._request_registry.unregister(register_key)

    async def _map_agent_event(
        self,
        agent_event: AgentEvent,
        data: Any,
        emit: Callable[..., Any],
    ) -> ServerStreamEvent | None:
        done_reason = ""
        done_content = ""
        error_message = ""
        if isinstance(data, dict):
            done_reason = data.get("reason", "") or ""
            done_content = data.get("content", "") or ""
            error_message = data.get("message", "") or ""
        elif isinstance(data, str):
            done_content = data
            error_message = data

        if agent_event == AgentEvent.SESSION:
            return await emit(SessionStartedEvent, SessionStartedEventData, session_id=data)
        if agent_event in (AgentEvent.START, AgentEvent.TURN_START, AgentEvent.TURN_END):
            return None
        if agent_event == AgentEvent.LLM_REQUEST_START:
            return await emit(ResponseStartedEvent, ResponseStartedEventData)
        if agent_event in (AgentEvent.TEXT_DELTA_START, AgentEvent.TEXT_DELTA_COMPLETED, AgentEvent.REASONING_END):
            return None
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
            if done_reason == "stopped" or done_content == "Stopped by user":
                return await emit(
                    ResponseCancelledEvent,
                    ResponseCancelledEventData,
                    message=done_content,
                )
            if done_reason == "requires_input" or done_content == "User input required":
                return await emit(
                    InputRequiredEvent,
                    InputRequiredEventData,
                    message=done_content,
                )
            if done_reason == "tool_failed":
                return await emit(
                    ResponseErrorEvent,
                    ResponseErrorEventData,
                    message=done_content,
                )
            return await emit(
                ResponseCompletedEvent,
                ResponseCompletedEventData,
                content=done_content,
            )
        if agent_event == AgentEvent.ERROR:
            return await emit(
                ResponseErrorEvent,
                ResponseErrorEventData,
                message=error_message or str(data),
            )
        return None
