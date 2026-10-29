import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from nova.agent.background import AgentBackground
from nova.agent.compaction import CompactionController, CompactionError
from nova.agent.events import (
    AgentEvent,
    EventBus,
)
from nova.agent.events import (
    done_payload as _done_payload,
)
from nova.agent.events import (
    error_payload as _error_payload,
)
from nova.agent.hierarchy import AgentHierarchy
from nova.agent.llm_stream import TurnOutcome, TurnStreamReader
from nova.agent.messaging import AgentMessaging
from nova.agent.session import AgentSession
from nova.agent.tool_guardrails import ToolGuardrails
from nova.agent.tool_invoker import ToolInvoker, has_parsable_arguments
from nova.agent.toolset import ToolsetBuilder
from nova.constants import DEFAULT_AGENT_KEY
from nova.db import DataSourceProtocol, get_default_data_source
from nova.llm import ChatStreamEvent, LLMProvider, ToolCall
from nova.llm.images import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES_BYTES,
    image_data_url,
    image_size_bytes,
)
from nova.prompt import PromptBuilder, PromptConfig
from nova.session import get_session_manager
from nova.session.models import encode_display_text
from nova.session.protocol import SessionProtocol
from nova.skills.service import SkillService
from nova.tools.approval import get_approval_manager
from nova.tools.checkpoints import begin_turn
from nova.tools.registry import ToolRegistry

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
        dropped with a warning rather than failing the whole message.
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
                image_data.append(image_data_url(image_url))
        elif attachment.get("type") == "document":
            for content_part in attachment.get("content", []):
                if content_part.get("type") == "text":
                    message_text = content_part.get("text", "") + "\n\n" + message_text
    return (
        message_text,
        image_data,
        display_text if display_text is not None else user_input,
    )


class Agent:
    """Nova agent: chat stream, tool use, session management."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        llm_provider: LLMProvider | None = None,
        review_llm: LLMProvider | None = None,
        review_model: str = "",
        session_manager: SessionProtocol | None = None,
        agent_key: str = DEFAULT_AGENT_KEY,
        agent_dir: Path | None = None,
        parent_agent: Optional["Agent"] = None,
        is_sub_agent: bool = False,
        depth: int = 0,
        allowed_tools: frozenset[str] | None = None,
        prompt_config: PromptConfig | None = None,
        data_source: DataSourceProtocol | None = None,
        on_title_updated: Callable[[str, str], None] | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.agent_key = agent_key
        self.llm = llm_provider
        # Optional separate provider for the permission reviewer. None means "use
        # the agent's own", which is the default and the previous behaviour.
        self._review_llm = review_llm
        self._review_model = review_model
        self.session = session_manager or get_session_manager()
        self._data_source = data_source
        self._on_title_updated = on_title_updated
        self.tool_registry = ToolRegistry()
        self._events = EventBus()
        self.parent_agent = parent_agent
        self.is_sub_agent = is_sub_agent
        self.depth = depth
        self.allowed_tools = allowed_tools
        self._hierarchy = AgentHierarchy(
            agent_key=agent_key,
            data_source=data_source,
            parent_agent=parent_agent,
        )

        if agent_dir is None:
            agent_dir = Path.home() / ".nova" / "agents" / agent_key
        agent_dir.mkdir(parents=True, exist_ok=True)
        self.agent_dir = agent_dir
        self._skill_service = self._build_skill_service(agent_key, agent_dir)
        self._skill_service.scan_skills()
        self._prompt_builder = PromptBuilder(
            prompt_config or PromptConfig.from_agent_dir(agent_dir)
        )
        self._abort_event = asyncio.Event()
        self._base_system_prompt: str | None = None
        self._active_workspace: str | None = None
        self._last_user_input: str = ""
        self._skill_tools: Any = None
        self._compaction = CompactionController(
            model=self.config.model, provider=self.config.provider
        )

        self._turns_since_review = 0
        # Fire-and-forget work (title generation, memory review) is reachable
        # from a turn, so these tasks need a strong reference for as long as
        # they run: asyncio only holds a weak one, and a collected task is
        # silently dropped mid-flight.
        self._background_tasks: set[asyncio.Task] = set()
        # One compact-and-retry per user request. A second overflow means the
        # fixed prompt alone does not fit, which retrying cannot fix.
        self._overflow_recovered = False
        self._guardrails = ToolGuardrails()
        self._approval = get_approval_manager()

        # Closed learning loop (opt-in). The loop is shared per agent key: a
        # new Agent is built per request, so a loop held on the agent would
        # reset its turn counter every turn and never reach the nudge interval.
        from nova.settings import get_settings

        _settings = get_settings()
        self._learning_loop = None
        if (
            getattr(_settings, "learning", None) is not None
            and _settings.learning.enabled
        ):
            from nova.learning.loop import get_learning_loop

            skills_dir = (
                self._skill_service.skills_dir
                if hasattr(self._skill_service, "skills_dir")
                else (self.agent_dir / "skills")
            )
            self._learning_loop = get_learning_loop(
                agent_key,
                settings=_settings.learning,
                skills_dir=skills_dir,
                db_path=str(_settings.database_path),
                llm=self.llm,
                model=self.config.model,
            )

        # AgentContext: shared state for composed services (long-term direction).
        from nova.agent.context import AgentContext

        self.ctx = AgentContext(
            agent=self,
            agent_key=self.agent_key,
            agent_dir=self.agent_dir,
            session=self.session,
            llm=self.llm,
            config=self.config,
            skill_service=self._skill_service,
            tool_registry=self.tool_registry,
            approval=self._approval,
            events=self._events,
            background_tasks=self._background_tasks,
            learning_loop=self._learning_loop,
            on_title_updated=self._on_title_updated,
            data_source=self._data_source,
            is_sub_agent=self.is_sub_agent,
            review_llm=self._review_llm,
            review_model=self._review_model,
            allowed_tools=self.allowed_tools,
            prompt_builder=self._prompt_builder,
            compaction=self._compaction,
            guardrails=self._guardrails,
        )
        # Composed services. Created after the context so they can read it.
        self.messaging = AgentMessaging(self)
        self.background = AgentBackground(self)
        self.session_service = AgentSession(self)

    @staticmethod
    def _build_skill_service(agent_key: str, agent_dir: Path) -> SkillService:
        if agent_key == DEFAULT_AGENT_KEY:
            return SkillService(skills_dir=agent_dir.parent.parent / "skills")
        return SkillService(
            skills_dir=agent_dir / "skills",
            fallback_dir=Path.home() / ".nova" / "skills",
        )

    def interrupt(self) -> None:
        """Interrupt the current execution; the user can trigger this at any time."""
        self._abort_event.set()
        log.info("Agent interrupted")

    def resolve_approval(
        self, approval_request_id: str, approved: bool, remember: bool = False
    ) -> bool:
        """Resolve a pending approval request (called from server route)."""
        return self._approval.resolve(approval_request_id, approved, remember)

    async def _stop_if_aborted(self) -> dict[str, Any] | None:
        """Return a done payload when execution should stop."""
        if self._abort_event.is_set():
            payload = _done_payload("stopped", "Stopped by user")
            await self._emit(AgentEvent.DONE, payload)
            return payload
        return None

    def on(self, event: AgentEvent, handler: Callable) -> None:
        self._events.on(event, handler)

    def off(self, event: AgentEvent, handler: Callable) -> None:
        self._events.off(event, handler)

    async def _emit(
        self, event: AgentEvent, data: dict[str, Any] | str | ToolCall | None = None
    ) -> None:
        await self._events.emit(event, data)

    async def _emit_approval(self, data: dict) -> None:
        await self._emit(AgentEvent.APPROVAL_REQUIRED, data)

    async def _run_turn(
        self,
        turn_count: int,
        tool_schemas: list[dict[str, Any]] | None,
        group_id: str | None = None,
        loaded_messages: list | None = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        stop_payload = await self._stop_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return

        reader = TurnStreamReader(
            emit=self._emit,
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
                await self.session_service._persist_failed_turn(reader, group_id)
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
        await self.session_service._persist_assistant_message(
            reader, tool_calls, group_id
        )

        if not tool_calls:
            payload = _done_payload("completed", reader.final_content)
            await self._emit(AgentEvent.DONE, payload)
            log.info(
                f"[Turn {turn_count}] Completed tokens_in={reader.tokens_input} "
                f"tokens_out={reader.tokens_output} "
                f"cache_read={reader.cache_read_tokens}"
            )
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
        return self.llm.chat_stream(
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
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        self._abort_event.clear()
        # Per-request latch: one compact-and-retry per user request. Reset here,
        # not only in __init__, so a reused Agent still recovers on later requests.
        self._overflow_recovered = False

        current_session = await self.session_service.resolve_session(
            session_id, user_input, workspace_dir, project_id
        )
        session_id = current_session.id if current_session else ""
        self.messaging.apply_active_workspace(current_session)

        yield AgentEvent.SESSION, session_id
        await self._emit(AgentEvent.START, user_input)
        yield AgentEvent.START, user_input

        message_text, image_data, display = build_user_message(
            user_input, attachments, display_text
        )
        self._last_user_input = message_text
        log.info(
            "[Session %s] Chat start agent=%s provider=%s model=%s workspace=%s "
            "input_chars=%d attachments=%d",
            session_id,
            self.agent_key,
            self.config.provider,
            self.config.model,
            self._active_workspace or "",
            len(message_text),
            len(attachments or []),
        )
        user_message = await self.session.add_message(
            role="user",
            content=message_text,
            images=image_data or None,
            variant=message_variant,
            data=encode_display_text(display, message_text),
        )
        # The turn's own user message is the rewind point: the client already
        # has its id, so `/rewind` can name the same moment the transcript does.
        begin_turn(
            session_id=session_id,
            checkpoint_id=user_message.id,
            label=display or message_text,
            workspace=self._active_workspace,
        )

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
        for _ in range(self.config.max_iterations):
            turn_count += 1
            if turn_count > 1:
                session_messages = await self.session.get_messages()

            # Context pressure is re-checked before every model call, not once per
            # request: a single request can run many tool turns and each tool
            # result can be arbitrarily large, so a request that started well
            # inside the window can overrun it halfway through.
            await self.session_service._record_session_route(data_source)
            try:
                async for event, data in self._compaction.maybe_compact(
                    session_messages,
                    current_session,
                    data_source,
                    self.llm,
                    self._emit,
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
            await self._emit(AgentEvent.TURN_START, {"turn": turn_count})
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
                    if self.session_service._try_overflow_recovery(message):
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
                await self._emit(AgentEvent.TURN_END, {"turn": turn_count})
                yield AgentEvent.TURN_END, {"turn": turn_count}
                continue

            log.info("[Turn %d] End", turn_count)
            await self._emit(AgentEvent.TURN_END, {"turn": turn_count})
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
                    self.background._maybe_schedule_memory_review()
                await self.background.schedule_request_learning(
                    request_tool_calls, request_messages_before
                )
                await self._emit(AgentEvent.DONE, done_payload)
                yield AgentEvent.DONE, done_payload
                return

        error_payload = _error_payload("max_iterations", "Maximum iterations reached")
        await self._emit(AgentEvent.ERROR, error_payload)
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
            self._emit,
            tools=self.tool_registry.get_schema() if self.tool_registry.tools else None,
        ):
            pass
        return {"compacted": self._compaction.compacted}

    async def _refresh_memory_index(self) -> None:
        """Build the memory index from DB for system prompt inclusion.

        Queries the memories visible to this agent and stores a compact
        listing in PromptConfig.memory_index. Built once per session (when
        _base_system_prompt is None) and then frozen: memory written mid-session
        lands in the store but is not re-injected until the next session, so the
        cached system prefix stays byte-stable for prompt caching.
        """
        if self.is_sub_agent:
            self._prompt_builder.config.memory_index = ""
            return
        try:
            from nova.memory.context import build_memory_index_for_system
            from nova.memory.service import MemoryService

            self._prompt_builder.config.memory_index = (
                await build_memory_index_for_system(
                    service=MemoryService(data_source=self._data_source),
                    agent_key=self.agent_key,
                )
            )
        except Exception as error:
            log.warning("Failed to refresh memory index: %s", error)

    async def _refresh_subagent_roster(self) -> None:
        """List this agent's delegatable sub-agents for the system prompt.

        Only a primary agent can delegate, so sub-agents get an empty roster.
        The roster is the current agent's children (agent_parents M2M), each
        rendered with its key, access level, and description so the model knows
        exactly which `target` values `delegate_to_agent` accepts.
        """
        if self.is_sub_agent:
            self._prompt_builder.config.subagent_roster = ""
            return
        try:
            children = await self._hierarchy.child_agent_records()
        except Exception as error:
            log.warning("Failed to refresh sub-agent roster: %s", error)
            children = []
        lines = []
        for child in children:
            key = child.get("key")
            if not key:
                continue
            access = (
                "read-only" if child.get("posture") == "read_only" else "full access"
            )
            description = (child.get("description") or "").strip() or "(no description)"
            lines.append(f"- `{key}` ({access}): {description}")
        self._prompt_builder.config.subagent_roster = "\n".join(lines)

    def add_sub_agent(self, sub_agent: "Agent") -> None:
        """Add a sub-agent to this agent's list of sub-agents."""
        self._hierarchy.add_sub_agent(self, sub_agent)

    def get_sub_agents(self) -> list["Agent"]:
        """Get all sub-agents of this agent."""
        return self._hierarchy.sub_agents()

    def get_runtime_parent(self) -> Optional["Agent"]:
        """Get the parent agent this instance is mounted under (in-memory, single)."""
        return self.parent_agent

    async def get_sub_agent_records(self) -> list[dict]:
        """Get child agent rows from the database (may differ from live sub-agents)."""
        return await self._hierarchy.child_agent_records()

    async def get_parent_agent_records(self) -> list[dict]:
        """Get all parent agent rows from the database (M2M; may be multiple)."""
        return await self._hierarchy.parent_agent_records()

    async def get_primary_parent_record(self) -> dict | None:
        """Get the first parent agent row from the database.

        This is the database's ordering, not necessarily the same parent
        as get_runtime_parent() returns; the two models are not guaranteed
        to agree.
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
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        invoker = ToolInvoker(
            registry=self.tool_registry,
            session=self.session,
            approval=self._approval,
            guardrails=self._guardrails,
            llm=self.llm,
            model=self.config.model,
            provider=self.config.provider,
            abort_event=self._abort_event,
            emit=self._emit,
            emit_approval=self._emit_approval,
            stop_if_aborted=self._stop_if_aborted,
            turn_count=turn_count,
        )
        async for event, data in invoker.run(tool_calls, group_id=group_id):
            yield event, data

    def register_tool(self, func: Callable, name: str | None = None) -> None:
        self.tool_registry.register(func, name)

    async def register_all_tools(self) -> None:
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
        )
        await builder.build()
        self._skill_tools = builder.skill_tools
