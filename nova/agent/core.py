import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

from nova.llm import LLMProvider, Message as LLMMessage
from nova.session import get_session_manager
from nova.session.protocol import SessionProtocol
from nova.tools.registry import ToolRegistry, tool
from nova.prompt import PromptBuilder, PromptConfig
from nova.agent.compaction import CompactionController
from nova.db import DataSourceProtocol, get_default_data_source
from nova.skills.service import SkillService
from nova.constants import DEFAULT_AGENT_KEY
from nova.agent.tool_guardrails import ToolGuardrails
from nova.agent.reasoning_timeouts import get_reasoning_timeout
from nova.tools.approval import ApprovalManager
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
    compress_threshold: int = 50
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
        prompt_config: Optional[PromptConfig] = None,
        data_source: Optional[DataSourceProtocol] = None,
    ):
        self.config = config or AgentConfig()
        self.agent_key = agent_key
        self.llm = llm_provider
        self.session = session_manager or get_session_manager()
        self._data_source = data_source
        self.tool_registry = ToolRegistry()
        self._events = EventBus()
        self.parent_agent = parent_agent
        self.is_sub_agent = is_sub_agent
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
        self._memory_modified_this_turn: bool = False
        self._last_user_input: str = ""
        self._skill_tools: Any = None
        self._compaction = CompactionController(
            model=self.config.model, provider=self.config.provider)

        self._turns_since_review = 0
        self._guardrails = ToolGuardrails()
        self._approval = ApprovalManager()

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

    def _check_abort(self) -> bool:
        """Check whether execution has been interrupted."""
        return self._abort_event.is_set()

    async def _wait_if_aborted(self) -> Optional[dict[str, Any]]:
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

    def _build_system_prompt(self, session_ctx: Any = None) -> str:
        tool_schemas = self.tool_registry.get_schema() if self.tool_registry.tools else []
        available_skills = self._skill_service.list_skills()
        return self._prompt_builder.build(
            tools_schemas=tool_schemas,
            available_skills=available_skills,
            workspace_override=self._active_workspace,
        )

    def _apply_active_workspace(self, session_ctx: Any = None) -> None:
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

    async def _get_messages(self, loaded_messages: Optional[list] = None) -> list[LLMMessage]:
        session = self.session.get_current_session()

        if self._base_system_prompt is None:
            await self._refresh_memory_index()
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
        stop_payload = await self._wait_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return

        reader = TurnStreamReader(
            emit=self._emit,
            wait_if_aborted=self._wait_if_aborted,
            turn_count=turn_count,
        )
        async for event, data in reader.consume(
            await self._open_completion(turn_count, tool_schemas, loaded_messages)
        ):
            yield event, data
        if reader.outcome is not TurnOutcome.CONTINUE:
            return

        stop_payload = await self._wait_if_aborted()
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
            log.info(f"[Turn {turn_count}] Completed without tool calls")
            yield AgentEvent.DONE, payload
            return

        async for event, data in self._invoke_tools(tool_calls, group_id, turn_count):
            yield event, data

    async def _open_completion(
        self,
        turn_count: int,
        tool_schemas: Any,
        loaded_messages: Optional[list],
    ) -> Any:
        messages = await self._get_messages(loaded_messages=loaded_messages)
        reasoning_timeout = get_reasoning_timeout(self.config.model, default=120)
        log.info(
            f"[Turn {turn_count}] Calling model={self.config.model}, tools={len(tool_schemas) if tool_schemas else 0}, timeout={reasoning_timeout}")
        return self.llm.chat_stream(
            messages=messages,
            model=self.config.model,
            tools=tool_schemas,
            abort_event=self._abort_event,
            timeout=reasoning_timeout,
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
            wait_if_aborted=self._wait_if_aborted,
            turn_count=turn_count,
        )
        async for event, data in invoker.run(tool_calls, group_id=group_id):
            yield event, data
        if invoker.memory_modified:
            self._memory_modified_this_turn = True

    async def _resolve_session(
        self,
        session_id: Optional[str],
        user_input: str,
        workspace_dir: Optional[str],
    ) -> Any:
        """Load the requested session, creating one when it is absent."""
        if session_id and await self.session.load_session(session_id):
            return self.session.get_current_session()
        await self.session.create_session(
            persist=True,
            first_message=user_input,
            workspace_dir=workspace_dir,
        )
        return self.session.get_current_session()

    def _maybe_schedule_memory_review(self) -> None:
        if self.config.memory_review_interval <= 0:
            return
        self._turns_since_review += 1
        if self._turns_since_review < self.config.memory_review_interval:
            return
        self._turns_since_review = 0
        asyncio.create_task(self._background_memory_review())

    async def chat_stream(
        self,
        user_input: str,
        session_id: str | None = None,
        attachments: list[dict] | None = None,
        workspace_dir: str | None = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        self._abort_event.clear()

        current_session = await self._resolve_session(
            session_id, user_input, workspace_dir)
        session_id = current_session.id if current_session else ""
        self._apply_active_workspace(current_session)

        yield AgentEvent.SESSION, session_id
        await self._emit(AgentEvent.START, user_input)
        yield AgentEvent.START, user_input

        message_text, image_data = build_user_message(user_input, attachments)
        self._last_user_input = message_text
        await self.session.add_message(
            role="user",
            content=message_text,
            images=image_data or None,
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
                session_messages, current_session, data_source, self.llm, self._emit
            ):
                yield event, data
            if self._compaction.compacted:
                session_messages = await self.session.get_messages()

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
                    yield event, data
                    return
                else:
                    yield event, data

            await self._emit(AgentEvent.TURN_END, {"turn": turn_count})
            yield AgentEvent.TURN_END, {"turn": turn_count}

            if self._memory_modified_this_turn:
                self._base_system_prompt = None
                self._memory_modified_this_turn = False

            if done_payload is not None:
                if done_payload.get("reason") in ("completed", "requires_input"):
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
        )
        await builder.build()
        self._skill_tools = builder.skill_tools

    async def _refresh_memory_index(self) -> None:
        """Build the memory index from DB for system prompt inclusion.

        Queries user-scoped memories and stores a compact listing in
        PromptConfig.memory_index.  This is called once per session (when
        _base_system_prompt is None) and again after save/delete memory
        invalidates the cache.
        """
        try:
            from nova.memory.context import build_memory_index_for_system
            from nova.memory.service import MemoryService
            self._prompt_builder.config.memory_index = (
                await build_memory_index_for_system(
                    service=MemoryService(data_source=self._data_source)
                )
            )
        except Exception as error:
            log.warning("Failed to refresh memory index: %s", error)

    async def _background_memory_review(self) -> None:
        await MemoryReviewer(
            llm=self.llm,
            session=self.session,
            model=self.config.model,
            data_source=self._data_source,
        ).run()

    def add_sub_agent(self, sub_agent: "Agent") -> None:
        """Add a sub-agent to this agent's list of sub-agents."""
        self._hierarchy.add_sub_agent(self, sub_agent)

    def get_sub_agents(self) -> list["Agent"]:
        """Get all sub-agents of this agent."""
        return self._hierarchy.sub_agents()

    def get_parent_agent(self) -> Optional["Agent"]:
        """Get the parent agent (if this is a sub-agent)."""
        return self.parent_agent

    async def get_child_agents(self) -> list[dict]:
        """Get all child agents of this agent from database."""
        return await self._hierarchy.child_agent_records()

    async def get_parent_agents(self) -> list[dict]:
        """Get all parent agents of this agent from database."""
        return await self._hierarchy.parent_agent_records()

    async def get_parent_agent_config(self) -> Optional[dict]:
        """Get the first parent agent configuration from database."""
        return await self._hierarchy.first_parent_agent_record()
