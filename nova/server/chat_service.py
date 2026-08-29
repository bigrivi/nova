"""
Chat service that maps internal agent events to stable backend events.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Callable

from nova.agent import AgentEvent
from nova.app import build_agent
from nova.constants import DEFAULT_AGENT_KEY
from nova.db import DataSourceProtocol, get_default_data_source
from nova.server.ai_sdk_stream import AISDKStreamAdapter
from nova.server.request_registry import RequestRegistry
from nova.server.schemas import (
    ApprovalRequiredEvent,
    ApprovalRequiredEventData,
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


def _normalize_workspace_dir(workspace_dir: str | None) -> str | None:
    """Trim, expand ~, and resolve a workspace path; blank/None clears it."""
    if not workspace_dir or not workspace_dir.strip():
        return None
    from pathlib import Path

    try:
        return str(Path(workspace_dir.strip()).expanduser().resolve())
    except OSError:
        return workspace_dir.strip()


class ChatService:
    def __init__(self, settings: Settings, data_source: DataSourceProtocol | None = None) -> None:
        self._settings = settings
        self._request_registry = RequestRegistry()
        self._data_source = data_source

    async def _get_data_source(self) -> DataSourceProtocol:
        if self._data_source is None:
            self._data_source = await get_default_data_source()
        return self._data_source

    async def list_sessions(self, agent_key: str | None = None) -> SessionListResponse:
        data_source = await self._get_data_source()
        sessions = await data_source.get_all_sessions(agent_key=agent_key)
        items = [
            SessionSummary(
                id=session["id"],
                title=session.get("title"),
                updated_at=session.get("updated_at", 0),
                agent_key=session.get("agent_key", DEFAULT_AGENT_KEY),
                workspace_dir=session.get("workspace_dir"),
            )
            for session in sessions
        ]
        return SessionListResponse(items=items)

    async def rename_session(self, session_id: str, title: str) -> bool:
        data_source = await self._get_data_source()
        return await data_source.update_session_title(session_id, title)

    async def set_session_workspace(self, session_id: str, workspace_dir: str | None) -> bool:
        data_source = await self._get_data_source()
        normalized = _normalize_workspace_dir(workspace_dir)
        return await data_source.set_session_workspace(session_id, normalized)

    async def delete_session(self, session_id: str, delete_memories: bool = False) -> bool:
        data_source = await self._get_data_source()
        await self._request_registry.unregister(session_id)
        deleted = await data_source.delete_session(session_id)
        if deleted and delete_memories:
            from nova.memory.service import MemoryService

            await MemoryService().delete_by_session(session_id)
        return deleted

    async def list_messages(self, session_id: str) -> MessageListResponse:
        data_source = await self._get_data_source()
        messages = await get_user_visible_history(data_source, session_id)
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
                reasoning_elapsed_ms=message.reasoning_elapsed_ms,
                group_id=message.group_id,
            )
            for message in messages
        ]
        return MessageListResponse(items=items)

    async def get_context(self, session_id: str, provider: str | None = None, model: str | None = None) -> dict:
        from nova.agent.compaction import estimate_context_tokens, get_context_limit

        data_source = await self._get_data_source()
        # Use raw messages for accurate compaction-aligned estimation
        try:
            raw_messages = await data_source.get_messages(session_id)
        except Exception:
            raw_messages = []
        # Resolve provider/model: explicit query wins, else session's agent, else settings default
        if not provider or not model:
            try:
                session = await data_source.get_session(session_id)
                agent_key = session.get("agent_key") if session else None
                if agent_key:
                    from nova.config.service import ConfigService

                    service = ConfigService(self._settings)
                    agent = await service.get_agent(agent_key)
                    if agent:
                        provider = provider or agent.get("provider")
                        model = model or agent.get("model")
            except Exception:
                pass
        if not provider or not model:
            # Fallback to first configured provider/model
            first_provider = next(iter(self._settings.providers.keys()), None)
            if first_provider:
                provider = provider or first_provider
                model = model or next(iter(self._settings.providers[first_provider].models.keys()), "gpt-4o")
            else:
                provider = provider or "ollama"
                model = model or "gpt-4o"
        used = estimate_context_tokens(raw_messages, model or "unknown")
        limit = get_context_limit(model or "unknown", provider or "ollama")
        percent = int(used / limit * 100) if limit else 0
        return {"used": used, "limit": limit, "percent": percent, "message_count": len(raw_messages)}

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
            is_new_session=not request.session_id,
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
                workspace_dir=_normalize_workspace_dir(request.workspace_dir),
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
        if agent_event in (AgentEvent.START, AgentEvent.TURN_END):
            return None
        if agent_event == AgentEvent.TURN_START:
            return await emit(ResponseStartedEvent, ResponseStartedEventData)
        if agent_event in (
            AgentEvent.TEXT_START,
            AgentEvent.TEXT_END,
            AgentEvent.REASONING_START,
            AgentEvent.REASONING_END,
            AgentEvent.COMPACTION_START,
            AgentEvent.COMPACTION_END,
        ):
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
        if agent_event == AgentEvent.APPROVAL_REQUIRED:
            return await emit(
                ApprovalRequiredEvent,
                ApprovalRequiredEventData,
                request_id=data.get("id", ""),
                command=data.get("command", ""),
                description=data.get("description", ""),
            )
        if agent_event == AgentEvent.ERROR:
            return await emit(
                ResponseErrorEvent,
                ResponseErrorEventData,
                message=error_message or str(data),
            )
        return None
