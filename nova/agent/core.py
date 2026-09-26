import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

from nova.llm import LLMProvider, Message as LLMMessage
from nova.session import get_session_manager
from nova.session.manager import SessionContext, default_session_title
from nova.session.protocol import SessionProtocol
from nova.agent.title_generator import generate_session_title
from nova.tools.registry import ToolRegistry, tool
from nova.prompt import PromptBuilder, PromptConfig
from nova.agent.compaction import CompactionController
from nova.db import DataSourceProtocol, get_default_data_source
from nova.skills.service import SkillService
from nova.constants import DEFAULT_AGENT_KEY
from nova.agent.tool_guardrails import ToolGuardrails
from nova.agent.reasoning_timeouts import get_reasoning_timeout
from nova.tools.approval import get_approval_manager
from nova.settings import get_settings
from nova.agent.hierarchy import AgentHierarchy
from nova.agent.memory_review import MemoryReviewer
from nova.agent.toolset import ToolsetBuilder
from nova.agent.llm_stream import TurnStreamReader, TurnOutcome
from nova.agent.tool_invoker import (
    ToolInvoker, ToolOutcome, has_parsable_arguments)
from nova.agent.events import (
    AgentEvent,
    EventBus,
    done_payload as _done_payload,
    error_payload as _error_payload,
)

log = logging.getLogger(__name__)




@dataclass
class AgentConfig:
    # Model key as defined in config.json (e.g., "my-gemma")
    model: str = "gpt-4o"
    provider: str = "ollama"
    max_iterations: int = 100
    max_tokens: int = 8192
    temperature: float = 0.7
    tools: Optional[list] = None
    memory_review_interval: int = 10


def build_user_message(
    user_input: str,
    attachments: Optional[list[dict]] = None,
) -> tuple[str, list[str]]:
    """Fold attachments into the text and image payload of a user message.

    Documents are prepended to the prompt because the model reads them as
    context for the request; images travel separately as base64 data.
    """
    image_data: list[str] = []
    message_text = user_input
    for attachment in attachments or []:
        if attachment.get("type") == "image":
            for content_part in attachment.get("content", []):
                if content_part.get("type") != "image":
                    continue
                image_url = content_part.get("image", "")
                if image_url.startswith("data:"):
                    image_data.append(image_url.split(",", 1)[1])
        elif attachment.get("type") == "document":
            for content_part in attachment.get("content", []):
                if content_part.get("type") == "text":
                    message_text = content_part.get(
                        "text", "") + "\n\n" + message_text
    return message_text, image_data


class Agent:
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        llm_provider: Optional[LLMProvider] = None,
        session_manager: Optional[SessionProtocol] = None,
        agent_key: str = DEFAULT_AGENT_KEY,
        agent_dir: Optional[Path] = None,
        parent_agent: Optional["Agent"] = None,
        is_sub_agent: bool = False,
        depth: int = 0,
        allowed_tools: Optional[frozenset[str]] = None,
        prompt_config: Optional[PromptConfig] = None,
        data_source: Optional[DataSourceProtocol] = None,
        on_title_updated: Optional[Callable[[str, str], None]] = None,
    ):
        self.config = config or AgentConfig()
        self.agent_key = agent_key
        self.llm = llm_provider
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
            prompt_config or PromptConfig.from_agent_dir(agent_dir))

        self._abort_event = asyncio.Event()
        self._base_system_prompt: Optional[str] = None
        self._active_workspace: Optional[str] = None
        self._last_user_input: str = ""
        self._skill_tools: Any = None
        self._compaction = CompactionController(
            model=self.config.model, provider=self.config.provider)

        self._turns_since_review = 0
        self._guardrails = ToolGuardrails()
        self._approval = get_approval_manager()

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

    def resolve_approval(self, approval_request_id: str, approved: bool, remember: bool = False) -> bool:
        """Resolve a pending approval request (called from server route)."""
        return self._approval.resolve(approval_request_id, approved, remember)

    async def _stop_if_aborted(self) -> Optional[dict[str, Any]]:
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

    async def _emit(self, event: AgentEvent, data: Any = None) -> None:
        await self._events.emit(event, data)

    def _build_system_prompt(self, session_ctx: SessionContext = None) -> str:
        tool_schemas = self.tool_registry.get_schema() if self.tool_registry.tools else []
        available_skills = self._skill_service.list_skills()
        return self._prompt_builder.build(
            tools_schemas=tool_schemas,
            available_skills=available_skills,
            workspace_override=self._active_workspace,
        )

    def _apply_active_workspace(self, session_ctx: SessionContext = None) -> None:
        from nova.tools.workspace_context import set_active_workspace

        override = getattr(session_ctx, "workspace_dir", None) if session_ctx else None
        if override:
            resolved = Path(override).expanduser()
            try:
                resolved = resolved.resolve()
            except OSError:
                pass
            try:
                resolved.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            effective = str(resolved)
        else:
            effective = str(self.agent_dir)

        if effective != self._active_workspace:
            self._active_workspace = effective
            self._base_system_prompt = None
        set_active_workspace(effective)

    def _convert_to_llm_messages(self, loaded_messages: list) -> list[LLMMessage]:
        resolved_tool_call_ids = {
            loaded_message.tool_call_id
            for loaded_message in loaded_messages
            if loaded_message.role == "tool" and loaded_message.tool_call_id
        }
        declared_tool_call_ids: set[str] = set()
        for loaded_message in loaded_messages:
            if loaded_message.role == "assistant" and loaded_message.tool_calls:
                for tool_call in loaded_message.tool_calls:
                    tool_call_identifier = tool_call.get(
                        "id") if isinstance(tool_call, dict) else None
                    if tool_call_identifier:
                        declared_tool_call_ids.add(tool_call_identifier)

        converted_messages: list[LLMMessage] = []
        for loaded_message in loaded_messages:
            if loaded_message.role == "tool" and loaded_message.tool_call_id not in declared_tool_call_ids:
                continue
            llm_message = LLMMessage(
                role=loaded_message.role, content=loaded_message.content)
            if loaded_message.tool_calls:
                llm_message.tool_calls = [
                    tool_call for tool_call in loaded_message.tool_calls
                    if (isinstance(tool_call, dict) and tool_call.get("id")
                        and tool_call["id"] in resolved_tool_call_ids)
                ]
            if loaded_message.tool_call_id:
                llm_message.tool_call_id = loaded_message.tool_call_id
            if loaded_message.images:
                llm_message.images = loaded_message.images
            if loaded_message.reasoning_content:
                llm_message.reasoning_content = loaded_message.reasoning_content
            if loaded_message.provider_meta:
                llm_message.provider_meta = loaded_message.provider_meta
            if loaded_message.model:
                llm_message.model = loaded_message.model
            converted_messages.append(llm_message)
        return converted_messages

    async def _build_messages(self, loaded_messages: Optional[list] = None) -> list[LLMMessage]:
        session = self.session.get_current_session()

        if self._base_system_prompt is None:
            await self._refresh_memory_index()
            await self._refresh_subagent_roster()
            self._base_system_prompt = self._build_system_prompt(session)

        if loaded_messages is None:
            loaded_messages = await self.session.get_messages()
        return [LLMMessage(
            role="system", content=self._base_system_prompt)] + self._convert_to_llm_messages(loaded_messages)

    async def _emit_approval(self, data: dict) -> None:
        await self._emit(AgentEvent.APPROVAL_REQUIRED, data)

    async def _run_turn(
        self,
        turn_count: int,
        tool_schemas: Any,
        group_id: Optional[str] = None,
        loaded_messages: Optional[list] = None,
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
            await self._start_completion_stream(turn_count, tool_schemas, loaded_messages)
        ):
            yield event, data
        if reader.outcome is not TurnOutcome.CONTINUE:
            return

        stop_payload = await self._stop_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return
        log.info(
            f"[Turn {turn_count}] After LLM loop: accumulated_content={len(reader.content)}, tool_calls={len(reader.tool_calls)}")

        tool_calls = self._executable_tool_calls(
            reader.collected_tool_calls(), turn_count)
        for tool_call in tool_calls:
            log.info(
                f"[Turn {turn_count}] Calling tool: {tool_call.name}({tool_call.arguments})")
        await self._persist_assistant_message(reader, tool_calls, group_id)

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
        tool_schemas: Any,
        loaded_messages: Optional[list],
    ) -> AsyncGenerator[Any, None]:
        messages = await self._build_messages(loaded_messages=loaded_messages)
        reasoning_timeout = get_reasoning_timeout(self.config.model, default=120)
        current_session = self.session.get_current_session()
        session_id = current_session.id if current_session else None
        log.info(
            f"[Turn {turn_count}] Calling model={self.config.model}, tools={len(tool_schemas) if tool_schemas else 0}, timeout={reasoning_timeout}")
        return self.llm.chat_stream(
            messages=messages,
            model=self.config.model,
            tools=tool_schemas,
            abort_event=self._abort_event,
            timeout=reasoning_timeout,
            session_id=session_id,
        )

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

    async def _persist_assistant_message(
        self,
        reader: TurnStreamReader,
        tool_calls: list,
        group_id: Optional[str],
    ) -> None:
        await self.session.add_message(
            role="assistant",
            content=reader.final_content,
            tool_calls=[
                tool_call.model_dump() if hasattr(tool_call, "model_dump") else tool_call
                for tool_call in tool_calls
            ] or None,
            reasoning_content=reader.reasoning or None,
            group_id=group_id,
            reasoning_elapsed_ms=reader.reasoning_elapsed_ms,
            tokens_input=reader.tokens_input,
            tokens_output=reader.tokens_output,
            provider_meta=reader.provider_meta,
            model=self.config.model,
        )

    async def _invoke_tools(
        self,
        tool_calls: list,
        group_id: Optional[str],
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

    async def _resolve_session(
        self,
        session_id: Optional[str],
        user_input: str,
        workspace_dir: Optional[str],
        project_id: Optional[str] = None,
    ) -> SessionContext:
        """Load the requested session, creating one when it is absent."""
        if session_id and await self.session.load_session(session_id):
            current = self.session.get_current_session()
            log.info("[Session %s] Reused", session_id)
            return current
        await self.session.create_session(
            persist=True,
            first_message=user_input,
            agent_key=self.agent_key,
            workspace_dir=workspace_dir,
            project_id=project_id,
        )
        current = self.session.get_current_session()
        log.info("[Session %s] Created", current.id if current else "?")
        self._maybe_schedule_title_generation(current, user_input)
        return current

    def _maybe_schedule_title_generation(
        self, session: SessionContext, first_message: str
    ) -> None:
        """Kick off the background title rewrite for a brand new session.

        The auto-derived title is already persisted, so this only improves it.
        Sub-agents keep the default: their sessions are never surfaced.
        """
        if self.is_sub_agent or self._on_title_updated is None:
            return
        asyncio.create_task(
            self._generate_title_in_background(session, first_message)
        )

    async def _generate_title_in_background(
        self, session: SessionContext, first_message: str
    ) -> None:
        session_id = session.id
        try:
            tool_schemas = (
                self.tool_registry.get_schema() if self.tool_registry.tools else None
            )
            title = await generate_session_title(
                self.llm,
                first_message,
                self.config.model,
                session.id,
                tool_schemas,
            )
            if title is None:
                return
            applied = await self.session.apply_generated_title(
                session_id,
                title,
                default_session_title(first_message),
            )
            if not applied:
                log.info(
                    "[Session %s] Title left alone; the user renamed it", session_id
                )
                return
            log.info("[Session %s] Title regenerated: %r", session_id, title)
            self._on_title_updated(session_id, title)
        except Exception as exception:
            # Defence in depth: the generator swallows its own failures, so
            # reaching here means something unexpected. The default title
            # stays regardless.
            log.warning(
                "[Session %s] Title generation task failed: %s", session_id, exception
            )

    def _maybe_schedule_memory_review(self) -> None:
        if self.config.memory_review_interval <= 0:
            return
        self._turns_since_review += 1
        if self._turns_since_review < self.config.memory_review_interval:
            return
        self._turns_since_review = 0
        asyncio.create_task(self._run_memory_review())

    async def chat_stream(
        self,
        user_input: str,
        session_id: str | None = None,
        attachments: list[dict] | None = None,
        workspace_dir: str | None = None,
        project_id: str | None = None,
        message_variant: str | None = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        self._abort_event.clear()

        current_session = await self._resolve_session(
            session_id, user_input, workspace_dir, project_id)
        session_id = current_session.id if current_session else ""
        self._apply_active_workspace(current_session)

        yield AgentEvent.SESSION, session_id
        await self._emit(AgentEvent.START, user_input)
        yield AgentEvent.START, user_input

        message_text, image_data = build_user_message(user_input, attachments)
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
        await self.session.add_message(
            role="user",
            content=message_text,
            images=image_data or None,
            variant=message_variant,
        )

        tool_schemas = self.tool_registry.get_schema() if self.tool_registry.tools else None

        data_source = self._data_source or await get_default_data_source()
        session_messages = await self.session.get_messages()

        run_group_id = uuid.uuid4().hex
        turn_count = 0
        for _ in range(self.config.max_iterations):
            turn_count += 1
            if turn_count > 1:
                session_messages = await self.session.get_messages()

            # Context pressure is re-checked before every model call, not once per
            # request: a single request can run many tool turns and each tool
            # result can be arbitrarily large, so a request that started well
            # inside the window can overrun it halfway through.
            async for event, data in self._compaction.run_with_events(
                session_messages,
                current_session,
                data_source,
                self.llm,
                self._emit,
                tools=tool_schemas,
            ):
                yield event, data
            if self._compaction.compacted:
                session_messages = await self.session.get_messages()

            log.info("[Turn %d] Start", turn_count)
            await self._emit(AgentEvent.TURN_START, {"turn": turn_count})
            yield AgentEvent.TURN_START, {"turn": turn_count}

            done_payload = None
            async for event, data in self._run_turn(
                turn_count,
                tool_schemas,
                group_id=run_group_id,
                loaded_messages=session_messages,
            ):
                if event == AgentEvent.DONE:
                    done_payload = data
                elif event == AgentEvent.ERROR:
                    log.error(
                        "[Session %s] Agent error: %s",
                        session_id,
                        data.get("message") if isinstance(data, dict) else data,
                    )
                    yield event, data
                    return
                else:
                    yield event, data

            log.info("[Turn %d] End", turn_count)
            await self._emit(AgentEvent.TURN_END, {"turn": turn_count})
            yield AgentEvent.TURN_END, {"turn": turn_count}

            if done_payload is not None:
                reason = (
                    done_payload.get("reason", "")
                    if isinstance(done_payload, dict)
                    else ""
                )
                log.info("[Session %s] Done reason=%s", session_id, reason)
                if reason in ("completed", "requires_input"):
                    self._maybe_schedule_memory_review()
                await self._emit(AgentEvent.DONE, done_payload)
                yield AgentEvent.DONE, done_payload
                return

        error_payload = _error_payload(
            "max_iterations", "Maximum iterations reached")
        await self._emit(AgentEvent.ERROR, error_payload)
        log.warning(f"[Turn {turn_count}] Maximum iterations reached")
        yield AgentEvent.ERROR, error_payload

    def register_tool(self, func: Callable, name: str = None) -> None:
        self.tool_registry.register(func, name)

    async def register_all_tools(self) -> None:
        builder = ToolsetBuilder(
            registry=self.tool_registry,
            skill_service=self._skill_service,
            approval=self._approval,
            is_sub_agent=self.is_sub_agent,
            allowed_tools=self.allowed_tools,
            agent_key=self.agent_key,
        )
        await builder.build()
        self._skill_tools = builder.skill_tools

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
            access = "read-only" if child.get("posture") == "read_only" else "full access"
            description = (child.get("description") or "").strip() or "(no description)"
            lines.append(f"- `{key}` ({access}): {description}")
        self._prompt_builder.config.subagent_roster = "\n".join(lines)

    async def _run_memory_review(self) -> None:
        await MemoryReviewer(
            llm=self.llm,
            session=self.session,
            model=self.config.model,
            data_source=self._data_source,
            tools=(
                self.tool_registry.get_schema() if self.tool_registry.tools else None
            ),
        ).run()

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

    async def get_primary_parent_record(self) -> Optional[dict]:
        """Get the first parent agent row from the database.

        This is the database's ordering, not necessarily the same parent
        as get_runtime_parent() returns; the two models are not guaranteed
        to agree.
        """
        return await self._hierarchy.first_parent_agent_record()
