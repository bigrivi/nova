"""
Chat service that maps internal agent events to stable backend events.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Callable
from typing import Any, Literal

from fastapi import HTTPException

from nova.agent import AgentEvent
from nova.app import build_agent
from nova.db import DataSourceProtocol, get_default_data_source
from nova.project.service import ProjectService
from nova.server.ai_sdk_frames import iter_parts
from nova.server.ai_sdk_stream import AISDKStreamAdapter
from nova.server.pending_prompts import get_pending_prompt_registry
from nova.server.request_registry import RequestRegistry
from nova.server.schemas import (
    ChatRequest,
    ChatResponse,
)
from nova.server.session_service import SessionService, normalize_workspace_dir
from nova.server.stream_buffer import StreamBuffer
from nova.settings import Settings

log = logging.getLogger(__name__)


def _pending_questions(chunk: bytes) -> list[dict] | None:
    """The questions carried by a ``data-nova-input-required`` frame.

    ``ask_user`` ends the turn with its questions in the tool result, so there
    is no tool call left waiting to hold them. The registry is what lets a
    client that closed its tab discover them again.
    """
    if b"data-nova-input-required" not in chunk:
        return None
    payload = ""
    for line in chunk.decode("utf-8", "ignore").splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
    if not payload:
        return None
    try:
        frame = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(frame, dict) or frame.get("type") != "data-nova-input-required":
        return None
    data = frame.get("data")
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, str):
        return None
    try:
        parsed = json.loads(message)
    except json.JSONDecodeError:
        return None
    questions = parsed.get("questions") if isinstance(parsed, dict) else None
    return questions if isinstance(questions, list) else None


def _injected_message_variant(request: ChatRequest) -> str | None:
    """Tag a turn whose user message the server wrote, not the user.

    A sub-agent completion arrives as a headless turn seeded with the child's
    result. Both the persisted message and the live frame read this one
    function, so the chip a live client renders cannot drift from the one it
    renders after a reload.
    """
    return "subagent" if request.metadata.get("from_subagent") else None


class ChatService:
    def __init__(
        self,
        settings: Settings,
        data_source: DataSourceProtocol | None = None,
        request_registry: RequestRegistry | None = None,
        stream_buffer: StreamBuffer | None = None,
        on_title_updated: Callable[[str, str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._request_registry = request_registry or RequestRegistry()
        self._stream_buffer = stream_buffer or StreamBuffer()
        self._request_registry.attach_buffer(self._stream_buffer)
        self._data_source = data_source
        self._on_title_updated = on_title_updated
        self.session_service = SessionService(
            settings=settings,
            data_source=data_source,
            request_registry=self._request_registry,
            stream_buffer=self._stream_buffer,
        )

    @property
    def settings(self) -> Settings:
        return self._settings

    async def validate_regenerate(self, session_id: str) -> None:
        """Reject a regenerate request that cannot be served.

        Args:
            session_id: Session the client wants to re-run.

        Raises:
            HTTPException: 404 when the session is unknown, 400 when it has no
                user message to answer again.
        """
        route = await self.session_service.get_session_route(session_id)
        if route is None:
            raise HTTPException(
                status_code=404, detail=f"Session '{session_id}' not found"
            )
        messages = await self.session_service.list_messages(session_id)
        if not any(message.role == "user" for message in messages.items):
            raise HTTPException(
                status_code=400,
                detail="This session has no user message to regenerate.",
            )

    async def _active_workspace(self) -> str:
        """The workspace the tool axis is currently judging paths against.

        Read per approval rather than cached: the context is set once per turn
        from the session, so a long-lived service outlives several workspaces
        and a value captured at construction would name the wrong boundary.

        Returns:
            The workspace directory, or an empty string when none is active --
            which is the case where every path is undecidable, so the dialog
            shows that rather than showing nothing.
        """
        from nova.tools.workspace_context import get_active_workspace

        return get_active_workspace() or ""

    def update_settings(self, settings: Settings) -> None:
        """Swap in reloaded settings without discarding live streaming state.

        Config edits (add/update/delete provider or model) reload settings at
        runtime. Rebuilding the whole ChatService would drop the request
        registry, stream buffer and reaper, orphaning every in-flight parallel
        session (status/active/resume break, TTL eviction stops). Updating the
        settings in place keeps that runtime state intact.
        """
        self._settings = settings
        self.session_service.update_settings(settings)

    @property
    def request_registry(self) -> RequestRegistry:
        return self._request_registry

    @property
    def stream_buffer(self) -> StreamBuffer:
        return self._stream_buffer

    async def _get_data_source(self) -> DataSourceProtocol:
        if self._data_source is None:
            self._data_source = await get_default_data_source()
        return self._data_source

    async def interrupt(self, session_id: str) -> bool:
        interrupted = await self._request_registry.interrupt(session_id)
        if interrupted:
            try:
                self._stream_buffer.append(session_id, b'data: {"type":"abort"}\n\n')
            except Exception:
                log.exception("interrupt buffer append failed for %s", session_id)
            self._stream_buffer.mark_done(session_id)
        return interrupted

    async def chat(self, request: ChatRequest) -> ChatResponse:
        session_id = request.session_id
        streamed: list[str] = []
        status: Literal["completed", "cancelled", "input_required", "error"] | None = (
            None
        )
        message = ""
        async for part in iter_parts(self.chat_stream_ai_sdk(request)):
            kind = part.get("type")
            if kind == "data-nova-session":
                data = part.get("data")
                if isinstance(data, dict):
                    session_id = data.get("sessionId") or session_id
                continue
            if kind == "text-delta":
                streamed.append(str(part.get("delta") or ""))
                continue
            if kind == "finish":
                status = "completed"
            elif kind == "abort":
                status = "cancelled"
            elif kind == "error":
                status = "error"
                message = str(part.get("errorText") or "")
            elif kind == "data-nova-input-required":
                status = "input_required"
                data = part.get("data")
                if isinstance(data, dict):
                    message = str(data.get("message") or "")
            if status is not None:
                break
        if status is None:
            raise RuntimeError("Chat finished without a terminal event.")
        return ChatResponse(
            session_id=session_id,
            status=status,
            message=message or "".join(streamed),
        )

    async def chat_stream_ai_sdk(
        self, request: ChatRequest
    ) -> AsyncGenerator[bytes, None]:
        """Yield framed AI-SDK byte chunks via AISDKStreamAdapter.

        The single mapping path: every surface consumes these frames, so a new
        AgentEvent type is taught here once.
        """
        adapter = AISDKStreamAdapter(
            wake_variant=_injected_message_variant(request),
            wake_text=request.message,
        )
        resolved_session_id = request.session_id
        fallback_sequence = 0
        # A new user turn answers (or abandons) the previous question batch.
        if resolved_session_id:
            get_pending_prompt_registry().clear_ask(resolved_session_id)
        # Arm this turn's boundary up front so a stale cursor-0 resume returns
        # only this turn even if the previous turn never marked done (e.g. it
        # errored or was cancelled, both of which skip mark_done below).
        turn_armed = False
        if resolved_session_id:
            self._stream_buffer.begin_turn(resolved_session_id)
            turn_armed = True
        try:
            async for event, data in self._agent_event_stream(request):
                if event == AgentEvent.SESSION and data and not resolved_session_id:
                    resolved_session_id = (
                        data if isinstance(data, str) else resolved_session_id
                    )
                    if resolved_session_id and not turn_armed:
                        self._stream_buffer.begin_turn(resolved_session_id)
                        turn_armed = True
                for chunk in adapter.feed(event, data):
                    if resolved_session_id:
                        questions = _pending_questions(chunk)
                        if questions:
                            get_pending_prompt_registry().set_ask(
                                resolved_session_id, questions
                            )
                        if fallback_sequence:
                            self._stream_buffer.ensure_next(
                                resolved_session_id, fallback_sequence
                            )
                            fallback_sequence = 0
                        _, framed = self._stream_buffer.append(
                            resolved_session_id, chunk
                        )
                        yield framed
                    else:
                        fallback_sequence += 1
                        yield (
                            b"id: "
                            + str(fallback_sequence).encode("ascii")
                            + b"\n"
                            + chunk
                        )
        except Exception:
            if turn_armed and resolved_session_id:
                self._stream_buffer.abort_turn(resolved_session_id)
            raise
        if resolved_session_id:
            self._stream_buffer.mark_done(resolved_session_id)
            await self._request_registry.mark_done(resolved_session_id)

    async def _agent_event_stream(
        self,
        request: ChatRequest,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        agent = await build_agent(
            agent_key=request.agent_key,
            provider=request.provider,
            model=request.model,
            is_new_session=not request.session_id,
            on_title_updated=self._on_title_updated,
            session_id=request.session_id,
            reasoning_effort=request.reasoning_effort,
            permission_mode=request.permission_mode,
        )
        register_key = request.session_id
        if register_key:
            await self._request_registry.register(register_key, agent)
        attachment_dicts = [att.model_dump() for att in request.attachments]
        workspace_dir = normalize_workspace_dir(request.workspace_dir)
        project_id = request.project_id
        if project_id and not workspace_dir:
            project = await ProjectService(self._data_source).get_project(project_id)
            if project and project.get("path"):
                workspace_dir = project["path"]
        message_variant = _injected_message_variant(request)
        regenerate = bool(getattr(request, "regenerate", False))
        extra: dict[str, Any] = {"regenerate": True} if regenerate else {}
        early_interrupt_checked = False
        try:
            async for event, data in agent.chat_stream(
                request.message,
                session_id=request.session_id,
                attachments=attachment_dicts,
                workspace_dir=workspace_dir,
                project_id=project_id,
                message_variant=message_variant,
                display_text=request.display_text,
                **extra,
            ):
                if event == AgentEvent.SESSION and data and not register_key:
                    register_key = data
                    await self._request_registry.register(register_key, agent)
                if register_key and not early_interrupt_checked:
                    # The turn's start has reset the agent's abort event by now,
                    # so a cancel that arrived while the Agent was still being
                    # built is applied here instead of being erased by that reset.
                    early_interrupt_checked = True
                    if await self._request_registry.take_pending_interrupt(
                        register_key
                    ):
                        agent.interrupt()
                if register_key:
                    # A slot with no activity signal is indistinguishable from an
                    # abandoned one, and the reaper would drop a turn that is
                    # still producing frames.
                    self._request_registry.note_activity(register_key)
                yield event, data
        finally:
            if register_key:
                await self._request_registry.mark_done(register_key)
