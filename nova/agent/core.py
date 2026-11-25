from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from novakit.events import AgentEvent, AgentEventFrame, EventBus
from novakit.events import (
    done_payload as _done_payload,
)
from novakit.events import (
    error_payload as _error_payload,
)
from novakit.llm import ChatStreamEvent, LLMProvider
from novakit.llm.images import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES_BYTES,
    downscale_image,
    image_data_url,
    image_size_bytes,
)
from novakit.session.models import Message, decode_display_text, encode_display_text
from novakit.session.protocol import SessionProtocol
from novakit.tools.registry import ToolRegistry

from nova.agent.assembly import build_agent_dependencies
from nova.agent.background import AgentBackground
from nova.agent.compaction import CompactionError
from nova.agent.context import (
    AgentDependencies,
    AgentSessionContext,
    BackgroundContext,
    MessagingContext,
)
from nova.agent.llm_stream import TurnOutcome, TurnStreamReader
from nova.agent.messaging import AgentMessaging, count_user_turns
from nova.agent.session import AgentSession
from nova.agent.state import TurnState
from nova.agent.tool_invoker import ToolInvoker, has_parsable_arguments
from nova.agent.toolset import ToolsetBuilder
from nova.constants import DEFAULT_AGENT_KEY
from nova.db import DataSourceProtocol, get_default_data_source
from nova.prompt import PromptConfig
from nova.session.manager import SessionContext
from nova.tools.checkpoints import begin_turn

if TYPE_CHECKING:
    from nova.learning.loop import LearningLoop

log = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    # Model key as defined in config.json (e.g., "my-gemma")
    model: str = "gpt-4o"
    provider: str = "ollama"
    max_iterations: int = 100
    max_tokens: int = 8192
    temperature: float = 0.7
    tools: list | None = None
    memory_review_interval: int = 10
    # Reasoning level for this run. None means "whatever the model config
    # declares", which is also what a provider that has no such concept gets.
    reasoning_effort: str | None = None
    # Ask a model to review actions the rules flagged, instead of interrupting
    # the user for every one. Off by default: a review costs a model call, and a
    # reviewer that waves through something the user would have refused is a worse
    # failure than a prompt. Set from the ``approval_review`` block in config.json.
    shell_review: bool = False
    # What a command that needs approval gets when the rules say so and no grant
    # covers it. ``ask`` waits for a human; ``dontAsk`` refuses instead, for runs
    # with nobody at the keyboard. Read from ``mode`` in permissions.json -- the
    # security-policy file, next to the rules whose answer it changes.
    permission_mode: str = "ask"
    # When True, the shell tool refuses anything it cannot prove only reads.
    # Used by read-only agents that still get shell for inspection.
    shell_read_only: bool = False


def build_user_message(
    user_input: str,
    attachments: list[dict] | None = None,
    display_text: str | None = None,
) -> tuple[str, list[str], str]:
    """Fold attachments into the text and image payload of a user message.

    Documents are prepended to the prompt because the model reads them as
    context for the request; images travel separately as data URLs so the media
    type reaches the provider (providers used to be told every image was PNG).

    Args:
        user_input: The text the user typed.
        attachments: Attachment dicts from the client, if any.

    Returns:
        ``(message_text, image_data_urls, display_text)``. The first is what the
        model reads (documents inlined, references appended by the client); the
        last is what a transcript should show. Images over the size budget are
        dropped with a warning rather than failing the whole message, and the
        ones that survive are downscaled to what a provider would use anyway.
    """
    image_data: list[str] = []
    image_bytes = 0
    message_text = user_input
    for attachment in attachments or []:
        if attachment.get("type") == "image":
            for content_part in attachment.get("content", []):
                if content_part.get("type") != "image":
                    continue
                image_url = content_part.get("image", "")
                # Remote references cannot be inlined without fetching them.
                if not image_url or "://" in image_url:
                    continue
                size = image_size_bytes(image_url)
                if size > MAX_IMAGE_BYTES or image_bytes + size > MAX_IMAGES_BYTES:
                    log.warning(
                        "Dropping attachment image (%d bytes, budget %d)",
                        size,
                        MAX_IMAGES_BYTES,
                    )
                    continue
                image_bytes += size
                image_data.append(downscale_image(image_data_url(image_url)))
        elif attachment.get("type") == "document":
            for content_part in attachment.get("content", []):
                if content_part.get("type") == "text":
                    message_text = content_part.get("text", "") + "\n\n" + message_text
    return (
        message_text,
        image_data,
        display_text if display_text is not None else user_input,
    )


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


class Agent:
    """Nova agent runtime: one prepared dependency graph per request."""

    def __init__(
        self,
        dependencies: AgentDependencies,
        *,
        parent_agent: Agent | None = None,
        depth: int = 0,
    ) -> None:
        """Wire prepared dependencies without performing I/O or global lookups.

        Args:
            dependencies: Fully assembled runtime dependencies.
            parent_agent: In-memory parent used by hierarchy lookups.
            depth: Delegation depth for spawn limits.
        """
        self.config = dependencies.config
        self.agent_key = dependencies.agent_key
        self.agent_dir = dependencies.agent_dir
        self.llm = dependencies.llm
        self._review_llm = dependencies.review_llm
        self._review_model = dependencies.review_model
        self.session = dependencies.session
        self._data_source = dependencies.data_source
        self.tool_registry = dependencies.tool_registry
        self._events = dependencies.events
        self.parent_agent = parent_agent
        self.is_sub_agent = dependencies.is_sub_agent
        self.depth = depth
        self.allowed_tools = dependencies.allowed_tools
        self._hierarchy = dependencies.hierarchy
        self._skill_service = dependencies.skill_service
        self._prompt_builder = dependencies.prompt_builder
        self._compaction = dependencies.compaction
        self._guardrails = dependencies.guardrails
        self._approval = dependencies.approval
        self.learning_loop = dependencies.learning_loop

        self._abort_event = asyncio.Event()
        self.state = TurnState()
        self._skill_tools: Any = None
        # Fire-and-forget work needs a strong reference until it finishes.
        self._background_tasks: set[asyncio.Task] = set()

        self.messaging = AgentMessaging(
            MessagingContext(
                agent_dir=self.agent_dir,
                agent_key=self.agent_key,
                is_sub_agent=self.is_sub_agent,
                skill_service=self._skill_service,
                prompt_builder=self._prompt_builder,
                session=self.session,
                learning_loop=self.learning_loop,
            ),
            self.state,
        )
        self.background = AgentBackground(
            BackgroundContext(
                llm=self.llm,
                config=self.config,
                tool_registry=self.tool_registry,
                session=self.session,
                data_source=self._data_source,
                learning_loop=self.learning_loop,
                on_title_updated=dependencies.on_title_updated,
                is_sub_agent=self.is_sub_agent,
                background_tasks=self._background_tasks,
                agent_key=self.agent_key,
            )
        )
        self.session_service = AgentSession(
            AgentSessionContext(
                session=self.session,
                config=self.config,
                compaction=self._compaction,
                agent_key=self.agent_key,
            ),
            self.state,
            self.background,
        )

    @classmethod
    def create(
        cls,
        config: AgentConfig | None = None,
        llm_provider: LLMProvider | None = None,
        review_llm: LLMProvider | None = None,
        review_model: str = "",
        session_manager: SessionProtocol | None = None,
        agent_key: str = DEFAULT_AGENT_KEY,
        agent_dir: Path | None = None,
        parent_agent: Agent | None = None,
        is_sub_agent: bool = False,
        depth: int = 0,
        allowed_tools: frozenset[str] | None = None,
        prompt_config: PromptConfig | None = None,
        data_source: DataSourceProtocol | None = None,
        on_title_updated: Callable[[str, str], None] | None = None,
        *,
        tool_registry: ToolRegistry | None = None,
        events: EventBus | None = None,
        learning_loop: LearningLoop | None = None,
    ) -> Agent:
        """Assemble dependencies and construct an Agent.

        This is the public construction seam. ``__init__`` itself only wires
        already-prepared objects, so tests and alternate composition roots can
        provide fakes without touching the filesystem or process globals.

        Args:
            config: Runtime configuration.
            llm_provider: Completion provider.
            review_llm: Optional provider used by permission reviewers.
            review_model: Model used by the reviewer.
            session_manager: Session implementation.
            agent_key: Stable agent identity.
            agent_dir: Agent home directory.
            parent_agent: In-memory parent for hierarchy lookups.
            is_sub_agent: Whether this is a delegated child.
            depth: Delegation depth.
            allowed_tools: Optional tool allowlist.
            prompt_config: Identity and prompt inputs.
            data_source: Persistent store.
            on_title_updated: Callback for generated titles.
            tool_registry: Prepared registry, including cached toolsets.
            events: Prepared event bus.
            learning_loop: Explicit learning loop, primarily for tests.

        Returns:
            A fully wired Agent.
        """
        dependencies = build_agent_dependencies(
            config=config,
            llm_provider=llm_provider,
            review_llm=review_llm,
            review_model=review_model,
            session_manager=session_manager,
            agent_key=agent_key,
            agent_dir=agent_dir,
            parent_agent=parent_agent,
            is_sub_agent=is_sub_agent,
            allowed_tools=allowed_tools,
            prompt_config=prompt_config,
            data_source=data_source,
            on_title_updated=on_title_updated,
            tool_registry=tool_registry,
            events=events,
            learning_loop=learning_loop,
        )
        return cls(dependencies, parent_agent=parent_agent, depth=depth)

    def replace_tool_registry(self, registry: ToolRegistry) -> None:
        """Replace the registry and keep background work on the same object.

        ``tool_registry`` remains the single source of truth. Other composed
        services read it through this reference, so cached toolsets cannot leave
        title generation or memory review using a stale, empty registry.

        Args:
            registry: Prepared registry to install.
        """
        self.tool_registry = registry
        self.background.ctx.tool_registry = registry

    def rebind_skill_tools(self) -> None:
        """Bind skill tools to this agent after installing a cached registry.

        The cached tool functions belong to the agent that built the registry.
        Rebinding makes them close over this agent's skill service instead.
        """
        from nova.skills.tools import SkillTools

        self._skill_tools = SkillTools(self._skill_service)
        for name in ("list_skills", "load_skill", "install_skill"):
            if self.allowed_tools is None or name in self.allowed_tools:
                self.tool_registry.register(getattr(self._skill_tools, name), name=name)

    def interrupt(self) -> None:
        """Interrupt the current execution; the user can trigger this at any time."""
        self._abort_event.set()
        log.info("Agent interrupted")

    def resolve_approval(
        self, approval_request_id: str, approved: bool, remember: bool = False
    ) -> bool:
        """Resolve a pending approval request.

        Args:
            approval_request_id: Identifier returned in the approval event.
            approved: Whether the user allowed the action.
            remember: Persist the decision as a grant for future requests.

        Returns:
            True when the pending request was found and resolved.
        """
        return self._approval.resolve(approval_request_id, approved, remember)

    async def _stop_if_aborted(self) -> dict[str, Any] | None:
        """Return a done payload when execution should stop.

        Returns:
            The stopped payload after notifying subscribers, or None.
        """
        if self._abort_event.is_set():
            payload = _done_payload("stopped", "Stopped by user")
            await self._events.emit(AgentEvent.DONE, payload)
            return payload
        return None

    def on(self, event: AgentEvent, handler: Callable) -> None:
        """Subscribe to an in-process agent event.

        Args:
            event: Event to observe.
            handler: Sync or async callback invoked with event and payload.
        """
        self._events.on(event, handler)

    def off(self, event: AgentEvent, handler: Callable) -> None:
        """Remove an in-process event subscription.

        Args:
            event: Event previously subscribed to.
            handler: Callback to remove.
        """
        self._events.off(event, handler)

    async def _emit_approval(self, data: dict) -> None:
        await self._events.emit(AgentEvent.APPROVAL_REQUIRED, data)

    async def _run_turn(
        self,
        turn_count: int,
        tool_schemas: list[dict[str, Any]] | None,
        group_id: str | None = None,
        loaded_messages: list | None = None,
    ) -> AsyncGenerator[AgentEventFrame, None]:
        stop_payload = await self._stop_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return

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
                # Persist before handing the error out. The consumer treats an
                # error as terminal and returns, which abandons this generator
                # at the yield - so anything written after it would never run,
                # and the text the user watched arrive would be lost.
                await self.session_service.persist_failed_turn(reader, group_id)
            yield event, data
        if reader.outcome is not TurnOutcome.CONTINUE:
            return

        stop_payload = await self._stop_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return
        log.info(
            f"[Turn {turn_count}] After LLM loop: accumulated_content={len(reader.content)}, tool_calls={len(reader.tool_calls)}"
        )

        tool_calls = self._executable_tool_calls(
            reader.collected_tool_calls(), turn_count
        )
        self.normalize_tool_arguments(tool_calls)
        for tool_call in tool_calls:
            log.info(
                f"[Turn {turn_count}] Calling tool: {tool_call.name}({tool_call.arguments})"
            )
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
        messages = await self.messaging.build_messages(loaded_messages=loaded_messages)
        current_session = self.session.get_current_session()
        session_id = current_session.id if current_session else None
        log.info(
            f"[Turn {turn_count}] Calling model={self.config.model}, tools={len(tool_schemas) if tool_schemas else 0}, timeout={getattr(self.llm, 'timeout_seconds', None)}"
        )
        llm = self.llm
        if llm is None:
            raise RuntimeError("Agent has no LLM provider")
        return llm.chat_stream(
            messages=messages,
            model=self.config.model,
            tools=tool_schemas,
            abort_event=self._abort_event,
            session_id=session_id,
            reasoning_effort=self.config.reasoning_effort,
        )

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
        """Stream one user request through preparation, model turns and tools.

        Args:
            user_input: User text or document reference.
            session_id: Session to resume. A new session is created when omitted.
            attachments: Client attachment payloads.
            workspace_dir: Workspace associated with the request.
            project_id: Optional project associated with the workspace.
            message_variant: Client-defined message variant.
            display_text: Text shown in the transcript when it differs from the
                model-facing content.
            regenerate: Replace the last assistant response instead of appending
                a new user turn.

        Yields:
            Session, text, reasoning, tool and terminal event frames.

        Raises:
            ValueError: If regeneration is requested without a user turn.
            RuntimeError: If the Agent has no LLM provider.
        """
        self._abort_event.clear()
        # Per-request latch: one compact-and-retry per user request. Reset here,
        # not only in __init__, so a reused Agent still recovers on later requests.
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
        """Resolve the session and build the user message without emitting events.

        Args:
            user_input: Text supplied by the caller.
            session_id: Existing session to resume, or None to create one.
            options: Attachment, workspace, display and regeneration inputs.

        Returns:
            All state needed to announce, persist and run the request.

        Raises:
            ValueError: If regeneration is requested but no user turn exists.
        """
        current_session = await self.session_service.resolve_session(
            session_id,
            "" if options.regenerate else user_input,
            options.workspace_dir,
            options.project_id,
        )
        resolved_session_id = current_session.id if current_session else ""
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
            # Decoding and re-encoding a multi-megabyte photo takes long enough
            # to stall the loop this stream runs on.
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
        """Announce the request, persist its user message and open a checkpoint.

        Args:
            prepared: Session and message state produced by ``_prepare_request``.

        Yields:
            The session and start frames, in that order.

        Raises:
            RuntimeError: If neither regeneration nor persistence produced a
                user message.
        """
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
        if user_message is None:  # unreachable: every branch above sets it
            raise RuntimeError("chat turn has no user message")
        # The turn's own user message is the rewind point: the client already
        # has its id, so `/rewind` can name the same moment the transcript does.
        begin_turn(
            session_id=prepared.session_id,
            checkpoint_id=user_message.id,
            label=prepared.display or prepared.message_text,
            workspace=self.state.workspace,
        )

    async def _run_request(
        self, prepared: PreparedRequest
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Run compaction and model/tool turns until the request terminates.

        Args:
            prepared: Session and message state produced by ``_prepare_request``.

        Yields:
            Compaction, turn, tool and terminal event frames.

        Raises:
            RuntimeError: If no LLM provider is configured.
        """
        session_id = prepared.session_id
        current_session = prepared.current_session
        tool_schemas = (
            self.tool_registry.get_schema() if self.tool_registry.tools else None
        )

        data_source = self._data_source or await get_default_data_source()
        session_messages = await self.session.get_messages()

        run_group_id = uuid.uuid4().hex
        turn_count = 0
        # The learning loop reviews the whole user request, not each tool
        # round: one request may run several model turns, and reviewing each
        # would extract the same skill several times.
        request_tool_calls = 0
        request_messages_before = len(session_messages)
        # The route is decided before the turn starts and stays put for the whole
        # request, so it is stamped once here rather than before every model call.
        await self.session_service.record_session_route(data_source)
        for _ in range(self.config.max_iterations):
            turn_count += 1
            if turn_count > 1:
                session_messages = await self.session.get_messages()

            # Context pressure is re-checked before every model call, not once per
            # request: a single request can run many tool turns and each tool
            # result can be arbitrarily large, so a request that started well
            # inside the window can overrun it halfway through.
            llm = self.llm
            if llm is None:
                raise RuntimeError("Agent has no LLM provider")
            try:
                async for event, data in self._compaction.maybe_compact(
                    session_messages,
                    current_session,
                    data_source,
                    llm,
                    self._events.emit,
                    tools=tool_schemas,
                ):
                    yield event, data
            except CompactionError as error:
                # Compaction is load-bearing: a turn that must compact but cannot
                # would otherwise continue with an oversized history and fail
                # later for a murkier reason. Abort with an explicit error the
                # client can show.
                log.error("[Session %s] Compaction failed: %s", session_id, error)
                yield AgentEvent.ERROR, _error_payload("compaction_error", str(error))
                return
            if self._compaction.compacted:
                session_messages = await self.session.get_messages()

            log.info("[Turn %d] Start", turn_count)
            await self._events.emit(AgentEvent.TURN_START, {"turn": turn_count})
            yield AgentEvent.TURN_START, {"turn": turn_count}

            done_payload = None
            retry_after_compaction = False
            # Tool calls made in THIS turn, not the session's running total:
            # the skill extractor asks "was this turn complex", and a session
            # total answers that question about every turn before it.
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
                        # The provider refused the request as too large. The error
                        # is not surfaced: the client sees one turn, not a failure
                        # followed by a silent retry.
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
                # The rejected turn is over, so close it out; the retry opens a
                # new one, and the client's turn boundaries stay balanced.
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
        log.warning(f"[Turn {turn_count}] Maximum iterations reached")
        yield AgentEvent.ERROR, error_payload

    async def compact_now(self, session_id: str) -> dict[str, Any]:
        """Force one compaction pass on *session_id*, outside a turn.

        The same path a turn takes, with the overflow latch set: compaction then
        ignores the token threshold but still refuses when the history cannot be
        split safely, so a small session reports "not compacted" rather than
        rewriting anything.

        Args:
            session_id: Session to compact.

        Returns:
            ``{"compacted": bool}``.

        Raises:
            FileNotFoundError: when the session does not exist.
            RuntimeError: when the agent has no provider to summarise with.
        """
        if not await self.session.load_session(session_id):
            raise FileNotFoundError(f"Session {session_id} not found")
        current = self.session.get_current_session()
        if current is None:
            raise FileNotFoundError(f"Session {session_id} not found")
        if self.llm is None:
            raise RuntimeError("Agent has no LLM provider to compact with")

        data_source = self._data_source or await get_default_data_source()
        messages = await self.session.get_messages()
        self._compaction.force_next = True
        async for _event, _payload in self._compaction.maybe_compact(
            messages,
            current,
            data_source,
            self.llm,
            self._events.emit,
            tools=self.tool_registry.get_schema() if self.tool_registry.tools else None,
        ):
            pass
        return {"compacted": self._compaction.compacted}

    def add_sub_agent(self, sub_agent: Agent) -> None:
        """Add a sub-agent to this agent's in-memory hierarchy.

        Args:
            sub_agent: Child runtime to mount under this agent.
        """
        self._hierarchy.add_sub_agent(self, sub_agent)

    def get_sub_agents(self) -> list[Agent]:
        """Return the in-memory child agents.

        Returns:
            A copy of the current child list.
        """
        return self._hierarchy.sub_agents()

    def get_runtime_parent(self) -> Agent | None:
        """Return the in-memory parent, which may differ from persisted parents.

        Returns:
            The mounted parent runtime, or None.
        """
        return self.parent_agent

    async def get_sub_agent_records(self) -> list[dict]:
        """Return persisted child rows, which may differ from live children.

        Returns:
            Child records from the agent graph.
        """
        return await self._hierarchy.child_agent_records()

    async def get_parent_agent_records(self) -> list[dict]:
        """Return all persisted parent rows for this agent.

        Returns:
            Parent records from the many-to-many agent graph.
        """
        return await self._hierarchy.parent_agent_records()

    async def get_primary_parent_record(self) -> dict | None:
        """Get the first parent agent row from the database.

        This is the database's ordering, not necessarily the same parent
        as get_runtime_parent() returns; the two models are not guaranteed
        to agree.

        Returns:
            The first persisted parent record, or None.
        """
        return await self._hierarchy.first_parent_agent_record()

    def normalize_tool_arguments(self, tool_calls: list) -> None:
        """Repair model-supplied tool arguments in place, before they are used.

        Runs ahead of persisting the assistant message and ahead of announcing
        the call, so the stored record, the announcement a client renders, and
        the value the tool receives are all the same thing. A tool that quietly
        fills in a missing field would otherwise publish that repair only in its
        result, leaving the two frames describing one call differently -- which
        is how a question whose id the model omitted ended up announced without
        one and impossible to map an answer back to.

        Args:
            tool_calls: Model-produced calls to repair in place.
        """
        for tool_call in tool_calls:
            name = getattr(tool_call, "name", None)
            raw = getattr(tool_call, "arguments", None)
            if not name or not isinstance(raw, str) or not raw:
                continue
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError:
                continue  # reported where the unparsable call is dropped
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
        """Drop calls whose arguments cannot be parsed before execution.

        Args:
            tool_calls: Calls collected from the model stream.
            turn_count: Current model turn number for diagnostics.

        Returns:
            Calls with parsable JSON object arguments.
        """
        executable = []
        for tool_call in tool_calls:
            if has_parsable_arguments(tool_call):
                executable.append(tool_call)
            else:
                log.warning(
                    f"[Turn {turn_count}] Skipping tool call {tool_call.name} "
                    f"with invalid JSON arguments: {tool_call.arguments!r}"
                )
        return executable

    async def _invoke_tools(
        self,
        tool_calls: list,
        group_id: str | None,
        turn_count: int,
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Execute one model turn's tool calls and forward their event frames.

        Args:
            tool_calls: Valid, normalized calls to execute.
            group_id: Group shared by the model turn and its tool results.
            turn_count: Current model turn number for logs.

        Yields:
            Tool announcement, approval, result and terminal frames.

        Raises:
            RuntimeError: If no LLM provider is configured.
        """
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
            func: Tool callable carrying Nova tool metadata.
            name: Optional registry name override.
        """
        self.tool_registry.register(func, name)

    async def register_all_tools(self) -> None:
        """Build the configured builtin, skill, MCP and policy toolset."""
        from nova.tools.approval_review import build_reviewer
        from nova.tools.permissions import ensure_permissions_file, permissions_path
        from nova.tools.tool_policy import load_tool_policy

        # Written once per launch, before any tool call can consult it.
        ensure_permissions_file(permissions_path().parent)

        # One reviewer serves both axes: the shell consults it for a flagged
        # command, and any tool set to `ask` consults it before interrupting.
        reviewer = None
        if self.config.shell_review and not self.is_sub_agent:
            reviewer = build_reviewer(
                self._review_llm or self.llm,
                self._review_model or self.config.model,
            )

        builder = ToolsetBuilder(
            registry=self.tool_registry,
            skill_service=self._skill_service,
            approval=self._approval,
            is_sub_agent=self.is_sub_agent,
            allowed_tools=self.allowed_tools,
            agent_key=self.agent_key,
            reviewer=reviewer,
            tool_policy=load_tool_policy(permissions_path()),
            permission_mode=self.config.permission_mode,
            shell_read_only=self.config.shell_read_only,
            # Without this the loop exists but its tool is never registered, so
            # an enabled learning loop offers the agent nothing to search with.
            learning_loop=self.learning_loop,
        )
        await builder.build()
        self._skill_tools = builder.skill_tools
