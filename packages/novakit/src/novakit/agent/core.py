"""Standalone in-memory agent runtime shared with Nova through adapters."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from novakit.agent.compaction import CompactionError
from novakit.agent.config import AgentConfig, CoreConfig
from novakit.agent.messages import build_user_message, count_user_turns
from novakit.agent.ports import AgentPorts, BeginTurn, Compactor
from novakit.agent.services import NoopBackground, StaticPromptProvider
from novakit.agent.session import AgentSession, AgentSessionContext, BackgroundHooks
from novakit.agent.state import TurnState
from novakit.agent.tool_guardrails import ToolGuardrails
from novakit.agent.tool_invoker import ToolInvoker, has_parsable_arguments
from novakit.constants import DEFAULT_AGENT_KEY
from novakit.events import AgentEvent, AgentEventFrame, EventBus
from novakit.events import done_payload as _done_payload
from novakit.events import error_payload as _error_payload
from novakit.llm import ChatStreamEvent, LLMProvider
from novakit.session import InMemorySession
from novakit.session.models import (
    Message,
    SessionContext,
    decode_display_text,
    encode_display_text,
)
from novakit.session.protocol import SessionProtocol
from novakit.tools.approval import ApprovalManager, InMemoryApprovalManager
from novakit.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


class _Messaging(Protocol):
    def apply_active_workspace(self, session: SessionContext | None) -> None: ...

    async def build_messages(self, loaded_messages: list | None = None) -> list: ...


@dataclass
class AgentOptions:
    """Optional dependencies for a standalone in-memory agent."""

    session: SessionProtocol | None = None
    tools: ToolRegistry | None = None
    events: EventBus | None = None
    system_prompt: str = ""
    agent_key: str = DEFAULT_AGENT_KEY
    parent_agent: Agent | None = None
    is_sub_agent: bool = False
    depth: int = 0
    allowed_tools: frozenset[str] | None = None
    guardrails: ToolGuardrails | None = None
    ports: AgentPorts | None = None


@dataclass(frozen=True)
class AgentRuntimeDependencies:
    """Fully wired services supplied by a host adapter to the shared runtime."""

    config: CoreConfig
    llm: LLMProvider | None
    session: SessionProtocol
    tool_registry: ToolRegistry
    events: EventBus
    agent_key: str
    is_sub_agent: bool
    allowed_tools: frozenset[str] | None
    state: TurnState
    background_tasks: set[asyncio.Task]
    messaging: _Messaging
    background: BackgroundHooks
    session_service: AgentSession
    compactor: Compactor | None
    approval: ApprovalManager | None
    guardrails: ToolGuardrails | None
    begin_turn: BeginTurn


@dataclass(frozen=True)
class ChatOptions:
    """Optional inputs that shape one chat request."""

    attachments: list[dict] | None = None
    workspace_dir: str | None = None
    project_id: str | None = None
    message_variant: str | None = None
    display_text: str | None = None
    regenerate: bool = False


@dataclass(frozen=True)
class PreparedRequest:
    """User input and session state prepared before the model loop starts."""

    current_session: SessionContext
    session_id: str
    user_input: str
    message_text: str
    image_data: list[str]
    display: str
    user_message: Message | None
    stale_ids: list[str]
    regenerate: bool
    attachment_count: int
    message_variant: str | None


def _noop_begin_turn(
    session_id: str,
    checkpoint_id: str,
    label: str,
    workspace: str | None,
) -> None:
    """Do nothing when the host does not provide checkpoint recording.

    Args:
        session_id: Active session identifier.
        checkpoint_id: User message identifier.
        label: Display label for the turn.
        workspace: Active workspace, if any.
    """


class Agent:
    """Run model/tool turns against an injected or in-memory session."""

    def __init__(
        self,
        config: CoreConfig,
        llm: LLMProvider | None,
        *,
        options: AgentOptions | None = None,
    ) -> None:
        """Construct an agent without I/O or global lookups.

        Args:
            config: Runtime configuration.
            llm: Completion provider; a turn fails clearly when omitted.
            options: Optional session, tools, events, prompt, and host ports.
        """
        resolved = options or AgentOptions()
        ports = resolved.ports or AgentPorts()
        session = resolved.session or InMemorySession()
        state = TurnState()
        background_tasks: set[asyncio.Task] = set()
        background = NoopBackground()
        messaging = StaticPromptProvider(resolved.system_prompt, state, session)
        session_service = AgentSession(
            AgentSessionContext(
                session=session,
                config=config,
                compaction=ports.compactor,
                agent_key=resolved.agent_key,
            ),
            state,
            background,
        )
        self._initialize_runtime(
            AgentRuntimeDependencies(
                config=config,
                llm=llm,
                session=session,
                tool_registry=resolved.tools or ToolRegistry(),
                events=resolved.events or EventBus(),
                agent_key=resolved.agent_key,
                is_sub_agent=resolved.is_sub_agent,
                allowed_tools=resolved.allowed_tools,
                state=state,
                background_tasks=background_tasks,
                messaging=messaging,
                background=background,
                session_service=session_service,
                compactor=ports.compactor,
                approval=ports.approval or InMemoryApprovalManager(),
                guardrails=resolved.guardrails or ToolGuardrails(),
                begin_turn=ports.begin_turn or _noop_begin_turn,
            ),
            parent_agent=resolved.parent_agent,
            depth=resolved.depth,
        )

    def _initialize_runtime(
        self,
        dependencies: AgentRuntimeDependencies,
        *,
        parent_agent: Agent | None,
        depth: int,
    ) -> None:
        """Assign all runtime state from one fully assembled dependency graph.

        Args:
            dependencies: Services and objects prepared by the composition root.
            parent_agent: In-memory parent used by hierarchy lookups.
            depth: Delegation depth for spawn limits.
        """
        self.config = dependencies.config
        self.agent_key = dependencies.agent_key
        self.llm = dependencies.llm
        self.session = dependencies.session
        self.tool_registry = dependencies.tool_registry
        self._events = dependencies.events
        self.parent_agent = parent_agent
        self.is_sub_agent = dependencies.is_sub_agent
        self.depth = depth
        self.allowed_tools = dependencies.allowed_tools
        self.state = dependencies.state
        self._background_tasks = dependencies.background_tasks
        self.messaging = dependencies.messaging
        self.background = dependencies.background
        self.session_service = dependencies.session_service
        self._compactor = dependencies.compactor
        self._approval = dependencies.approval
        self._guardrails = dependencies.guardrails
        self._begin_turn = dependencies.begin_turn
        self._abort_event = asyncio.Event()

    def replace_tool_registry(self, registry: ToolRegistry) -> None:
        """Replace the active tool registry.

        Args:
            registry: Prepared registry to install.
        """
        self.tool_registry = registry

    def interrupt(self) -> None:
        """Interrupt the current execution."""
        self._abort_event.set()
        log.info("Agent interrupted")

    def resolve_approval(
        self, approval_request_id: str, approved: bool, remember: bool = False
    ) -> bool:
        """Resolve a pending approval when the host supplied a manager.

        Args:
            approval_request_id: Identifier returned in the approval event.
            approved: Whether the action is allowed.
            remember: Whether the manager should remember the decision.

        Returns:
            True when a pending request was found and resolved.
        """
        if self._approval is None:
            return False
        return self._approval.resolve(approval_request_id, approved, remember)

    async def _stop_if_aborted(self) -> dict[str, Any] | None:
        """Return a done payload when execution should stop."""
        if self._abort_event.is_set():
            payload = _done_payload("stopped", "Stopped by user")
            await self._events.emit(AgentEvent.DONE, payload)
            return payload
        return None

    def on(self, event: AgentEvent, handler: Callable[..., object]) -> None:
        """Subscribe to an in-process agent event.

        Args:
            event: Event to observe.
            handler: Sync or async callback invoked with event and payload.
        """
        self._events.on(event, handler)

    def off(self, event: AgentEvent, handler: Callable[..., object]) -> None:
        """Remove an in-process event subscription.

        Args:
            event: Event previously subscribed to.
            handler: Callback to remove.
        """
        self._events.off(event, handler)

    async def _emit_approval(self, data: dict) -> None:
        await self._events.emit(AgentEvent.APPROVAL_REQUIRED, data)

    async def chat_stream(
        self,
        user_input: str,
        session_id: str | None = None,
        attachments: list[dict] | None = None,
        workspace_dir: str | None = None,
        project_id: str | None = None,
        message_variant: str | None = None,
        display_text: str | None = None,
        regenerate: bool = False,
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Stream one user request through preparation, model turns, and tools.

        Args:
            user_input: User text or document reference.
            session_id: Session to resume; a new session is created when omitted.
            attachments: Client attachment payloads.
            workspace_dir: Workspace associated with the request.
            project_id: Optional project associated with the workspace.
            message_variant: Client-defined message variant.
            display_text: Transcript text when it differs from model-facing content.
            regenerate: Replace the last assistant response instead of appending.

        Yields:
            Session, text, reasoning, tool, and terminal event frames.

        Raises:
            ValueError: If regeneration is requested without a user turn.
            RuntimeError: If the agent has no LLM provider.
        """
        self._abort_event.clear()
        self.state.overflow_recovered = False
        prepared = await self._prepare_request(
            user_input,
            session_id,
            ChatOptions(
                attachments=attachments,
                workspace_dir=workspace_dir,
                project_id=project_id,
                message_variant=message_variant,
                display_text=display_text,
                regenerate=regenerate,
            ),
        )
        async for frame in self._start_request(prepared):
            yield frame
        async for frame in self._run_request(prepared):
            yield frame

    async def _prepare_request(
        self,
        user_input: str,
        session_id: str | None,
        options: ChatOptions,
    ) -> PreparedRequest:
        """Resolve the session and build the user message without emitting events."""
        current_session = await self.session_service.resolve_session(
            session_id,
            "" if options.regenerate else user_input,
            options.workspace_dir,
            options.project_id,
        )
        resolved_session_id = current_session.id
        self.messaging.apply_active_workspace(current_session)

        stale_ids: list[str] = []
        user_message: Message | None = None
        if options.regenerate:
            history = await self.session.get_messages()
            index = next(
                (
                    position
                    for position in range(len(history) - 1, -1, -1)
                    if history[position].role == "user"
                    and not history[position].summary
                ),
                None,
            )
            if index is None:
                raise ValueError("No user message to regenerate.")
            user_message = history[index]
            stale_ids = [message.id for message in history[index + 1 :]]
            message_text = user_message.content
            image_data = user_message.images or []
            display = decode_display_text(user_message.data) or message_text
            resolved_input = display
        else:
            message_text, image_data, display = await asyncio.to_thread(
                build_user_message,
                user_input,
                options.attachments,
                options.display_text,
            )
            resolved_input = user_input

        return PreparedRequest(
            current_session=current_session,
            session_id=resolved_session_id,
            user_input=resolved_input,
            message_text=message_text,
            image_data=image_data,
            display=display,
            user_message=user_message,
            stale_ids=stale_ids,
            regenerate=options.regenerate,
            attachment_count=len(options.attachments or []),
            message_variant=options.message_variant,
        )

    async def _start_request(
        self, prepared: PreparedRequest
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Announce and persist the user message, then open a host checkpoint."""
        yield AgentEvent.SESSION, prepared.session_id
        await self._events.emit(AgentEvent.START, prepared.user_input)
        yield AgentEvent.START, prepared.user_input

        log.info(
            "[Session %s] Chat start agent=%s provider=%s model=%s workspace=%s "
            "input_chars=%d attachments=%d regenerate=%s",
            prepared.session_id,
            self.agent_key,
            self.config.provider,
            self.config.model,
            self.state.workspace or "",
            len(prepared.message_text),
            prepared.attachment_count,
            prepared.regenerate,
        )
        user_message = prepared.user_message
        if prepared.regenerate:
            if prepared.stale_ids:
                await self.session.rollback_messages(
                    prepared.stale_ids, session_id=prepared.session_id
                )
        else:
            user_message = await self.session.add_message(
                role="user",
                content=prepared.message_text,
                images=prepared.image_data or None,
                variant=prepared.message_variant,
                data=encode_display_text(prepared.display, prepared.message_text),
            )
        if user_message is None:
            raise RuntimeError("chat turn has no user message")
        self._begin_turn(
            session_id=prepared.session_id,
            checkpoint_id=user_message.id,
            label=prepared.display or prepared.message_text,
            workspace=self.state.workspace,
        )

    async def _run_request(
        self, prepared: PreparedRequest
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Run compaction and model/tool turns until the request terminates."""
        session_id = prepared.session_id
        current_session = prepared.current_session
        tool_schemas = (
            self.tool_registry.get_schema() if self.tool_registry.tools else None
        )
        session_messages = await self.session.get_messages()
        run_group_id = uuid.uuid4().hex
        turn_count = 0
        request_tool_calls = 0
        request_messages_before = len(session_messages)
        await self.session_service.record_session_route()

        for _ in range(self.config.max_iterations):
            turn_count += 1
            if turn_count > 1:
                session_messages = await self.session.get_messages()

            llm = self.llm
            if llm is None:
                raise RuntimeError("Agent has no LLM provider")
            if self._compactor is not None:
                try:
                    async for event, data in self._compactor.maybe_compact(
                        session_messages,
                        current_session,
                        llm,
                        self._events.emit,
                        tools=tool_schemas,
                    ):
                        yield event, data
                except CompactionError as error:
                    log.error("[Session %s] Compaction failed: %s", session_id, error)
                    yield (
                        AgentEvent.ERROR,
                        _error_payload("compaction_error", str(error)),
                    )
                    return
                if self._compactor.compacted:
                    session_messages = await self.session.get_messages()

            log.info("[Turn %d] Start", turn_count)
            await self._events.emit(AgentEvent.TURN_START, {"turn": turn_count})
            yield AgentEvent.TURN_START, {"turn": turn_count}

            done_payload = None
            retry_after_compaction = False
            turn_tool_calls = 0
            async for event, data in self._run_turn(
                turn_count,
                tool_schemas,
                group_id=run_group_id,
                loaded_messages=session_messages,
            ):
                if event == AgentEvent.TOOL_CALL:
                    turn_tool_calls += 1
                if event == AgentEvent.DONE:
                    done_payload = data
                elif event == AgentEvent.ERROR:
                    message = data.get("message") if isinstance(data, dict) else data
                    if self.session_service.try_overflow_recovery(message):
                        retry_after_compaction = True
                        break
                    log.error(
                        "[Session %s] Agent error: %s",
                        session_id,
                        message,
                    )
                    yield event, data
                    return
                else:
                    yield event, data

            if retry_after_compaction:
                log.info(
                    "[Turn %d] End (rejected as too large; retrying after compaction)",
                    turn_count,
                )
                await self._events.emit(AgentEvent.TURN_END, {"turn": turn_count})
                yield AgentEvent.TURN_END, {"turn": turn_count}
                continue

            log.info("[Turn %d] End", turn_count)
            await self._events.emit(AgentEvent.TURN_END, {"turn": turn_count})
            yield AgentEvent.TURN_END, {"turn": turn_count}
            request_tool_calls += turn_tool_calls

            if done_payload is not None:
                reason = (
                    done_payload.get("reason", "")
                    if isinstance(done_payload, dict)
                    else ""
                )
                log.info("[Session %s] Done reason=%s", session_id, reason)
                if reason in ("completed", "requires_input"):
                    self.background.maybe_schedule_memory_review(
                        count_user_turns(session_messages)
                    )
                await self.background.schedule_request_learning(
                    request_tool_calls, request_messages_before
                )
                await self._events.emit(AgentEvent.DONE, done_payload)
                yield AgentEvent.DONE, done_payload
                return

        error_payload = _error_payload("max_iterations", "Maximum iterations reached")
        await self._events.emit(AgentEvent.ERROR, error_payload)
        log.warning("[Turn %d] Maximum iterations reached", turn_count)
        yield AgentEvent.ERROR, error_payload

    async def _run_turn(
        self,
        turn_count: int,
        tool_schemas: list[dict[str, Any]] | None,
        group_id: str | None = None,
        loaded_messages: list | None = None,
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Run one model response and any tool calls it requested."""
        stop_payload = await self._stop_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return

        from novakit.agent.llm_stream import TurnOutcome, TurnStreamReader

        reader = TurnStreamReader(
            emit=self._events.emit,
            stop_if_aborted=self._stop_if_aborted,
            turn_count=turn_count,
        )
        async for event, data in reader.consume(
            await self._start_completion_stream(
                turn_count, tool_schemas, loaded_messages
            )
        ):
            if event == AgentEvent.ERROR:
                await self.session_service.persist_failed_turn(reader, group_id)
            yield event, data
        if reader.outcome is not TurnOutcome.CONTINUE:
            return

        stop_payload = await self._stop_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return
        tool_calls = self._executable_tool_calls(
            reader.collected_tool_calls(), turn_count
        )
        self.normalize_tool_arguments(tool_calls)
        await self.session_service.persist_assistant_message(
            reader, tool_calls, group_id
        )
        if not tool_calls:
            payload = _done_payload("completed", reader.final_content)
            await self._events.emit(AgentEvent.DONE, payload)
            yield AgentEvent.DONE, payload
            return

        async for event, data in self._invoke_tools(tool_calls, group_id, turn_count):
            yield event, data

    async def _start_completion_stream(
        self,
        turn_count: int,
        tool_schemas: list[dict[str, Any]] | None,
        loaded_messages: list | None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """Build provider messages and open one model stream."""
        messages = await self.messaging.build_messages(loaded_messages=loaded_messages)
        current_session = self.session.get_current_session()
        session_id = current_session.id if current_session else None
        llm = self.llm
        if llm is None:
            raise RuntimeError("Agent has no LLM provider")
        log.info(
            "[Turn %d] Calling model=%s, tools=%d",
            turn_count,
            self.config.model,
            len(tool_schemas) if tool_schemas else 0,
        )
        return llm.chat_stream(
            messages=messages,
            model=self.config.model,
            tools=tool_schemas,
            abort_event=self._abort_event,
            session_id=session_id,
            reasoning_effort=self.config.reasoning_effort,
        )

    def normalize_tool_arguments(self, tool_calls: list) -> None:
        """Repair model-supplied tool arguments before persistence or execution."""
        for tool_call in tool_calls:
            name = getattr(tool_call, "name", None)
            raw = getattr(tool_call, "arguments", None)
            if not name or not isinstance(raw, str) or not raw:
                continue
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(arguments, dict):
                continue
            try:
                normalized = self.tool_registry.behavior_for(name).normalize_input(
                    arguments
                )
            except Exception:
                log.exception(
                    "normalize_input failed for tool %s; keeping raw arguments", name
                )
                continue
            if normalized != arguments:
                tool_call.arguments = json.dumps(normalized, ensure_ascii=False)

    def _executable_tool_calls(self, tool_calls: list, turn_count: int) -> list:
        """Drop calls whose arguments cannot be parsed before execution."""
        executable = []
        for tool_call in tool_calls:
            if has_parsable_arguments(tool_call):
                executable.append(tool_call)
            else:
                log.warning(
                    "[Turn %d] Skipping tool call %s with invalid JSON arguments: %r",
                    turn_count,
                    tool_call.name,
                    tool_call.arguments,
                )
        return executable

    async def _invoke_tools(
        self,
        tool_calls: list,
        group_id: str | None,
        turn_count: int,
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Execute one model turn's tool calls and forward their event frames."""
        llm = self.llm
        if llm is None:
            raise RuntimeError("Agent has no LLM provider")
        invoker = ToolInvoker(
            registry=self.tool_registry,
            session=self.session,
            approval=self._approval,
            guardrails=self._guardrails,
            llm=llm,
            model=self.config.model,
            provider=self.config.provider,
            abort_event=self._abort_event,
            emit=self._events.emit,
            emit_approval=self._emit_approval,
            stop_if_aborted=self._stop_if_aborted,
            turn_count=turn_count,
        )
        async for event, data in invoker.run(tool_calls, group_id=group_id):
            yield event, data

    def register_tool(self, func: Callable, name: str | None = None) -> None:
        """Register one tool for this agent.

        Args:
            func: Tool callable carrying optional registry metadata.
            name: Optional registry name override.
        """
        self.tool_registry.register(func, name)

    async def compact_now(self, session_id: str) -> dict[str, Any]:
        """Force one compaction pass outside a normal turn.

        Args:
            session_id: Session to compact.

        Returns:
            ``{"compacted": bool}``.

        Raises:
            FileNotFoundError: When the session does not exist.
            RuntimeError: When no provider is configured.
        """
        if not await self.session.load_session(session_id):
            raise FileNotFoundError(f"Session {session_id} not found")
        current = self.session.get_current_session()
        if current is None:
            raise FileNotFoundError(f"Session {session_id} not found")
        if self.llm is None:
            raise RuntimeError("Agent has no LLM provider to compact with")
        if self._compactor is None:
            return {"compacted": False}
        messages = await self.session.get_messages()
        self._compactor.force_next = True
        async for _event, _payload in self._compactor.maybe_compact(
            messages,
            current,
            self.llm,
            self._events.emit,
            tools=self.tool_registry.get_schema() if self.tool_registry.tools else None,
        ):
            pass
        return {"compacted": self._compactor.compacted}


__all__ = [
    "Agent",
    "AgentConfig",
    "AgentOptions",
    "AgentRuntimeDependencies",
    "ChatOptions",
    "CoreConfig",
    "PreparedRequest",
    "build_user_message",
]
