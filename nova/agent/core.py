import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

from nova.llm import LLMProvider, Message as LLMMessage, ToolCall, ToolResult
from nova.session import get_session_manager
from nova.session.protocol import SessionProtocol
from nova.tools.registry import ToolRegistry, tool
from nova.prompt import PromptBuilder, PromptConfig
from nova.agent.compaction import prepare_compaction, run_compaction_plan, get_context_limit
from nova.db.database import ensure_db
from nova.skills.service import SkillService
from nova.mcp.manager import MCPManager
from nova.settings import get_settings
from nova.constants import DEFAULT_AGENT_KEY
from nova.agent.tool_guardrails import ToolGuardrails, GuardrailAction
from nova.agent.reasoning_timeouts import get_reasoning_timeout
from nova.tools.approval import ApprovalManager
from nova.tools.shell import is_hardline, is_dangerous

log = logging.getLogger(__name__)


class AgentEvent(Enum):
    # Session lifecycle
    SESSION = "session"
    START = "start"
    DONE = "done"
    ERROR = "error"

    # Turn lifecycle
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # Reasoning stream
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"

    # Text stream
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"

    # Tool execution
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Context compaction
    COMPACTION_START = "compaction_start"
    COMPACTION_END = "compaction_end"

    # Danger command approval (desktop / CLI)
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_HEARTBEAT = "approval_heartbeat"
    APPROVAL_RESULT = "approval_result"


def _done_payload(reason: str, content: Optional[str] = None) -> dict[str, Any]:
    return {"reason": reason, "content": content}


def _error_payload(reason: str, message: str) -> dict[str, Any]:
    return {"reason": reason, "message": message}


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
    ):
        self.config = config or AgentConfig()
        self.agent_key = agent_key
        self.llm = llm_provider
        self.session = session_manager or get_session_manager()
        self.tool_registry = ToolRegistry()
        self._event_handlers: dict[AgentEvent, list[Callable]] = {}
        self.parent_agent = parent_agent
        self.is_sub_agent = is_sub_agent
        self._sub_agents: list["Agent"] = []

        if agent_dir is None:
            agent_dir = Path.home() / ".nova" / "agents" / agent_key
        agent_dir.mkdir(parents=True, exist_ok=True)
        if agent_key == DEFAULT_AGENT_KEY:
            skills_dir = agent_dir.parent.parent / "skills"
            self._skill_service = SkillService(skills_dir=skills_dir)
        else:
            skills_dir = agent_dir / "skills"
            global_skills = Path.home() / ".nova" / "skills"
            self._skill_service = SkillService(
                skills_dir=skills_dir, fallback_dir=global_skills)
        self._skill_service.scan_skills()
        if prompt_config is not None:
            self._prompt_builder = PromptBuilder(prompt_config)
        else:
            soul_content = (agent_dir / "SOUL.md").read_text(
                encoding="utf-8") if (agent_dir / "SOUL.md").exists() else ""
            identity_content = (agent_dir / "IDENTITY.md").read_text(
                encoding="utf-8").strip() if (agent_dir / "IDENTITY.md").exists() else ""
            user_content = (agent_dir / "USER.md").read_text(
                encoding="utf-8") if (agent_dir / "USER.md").exists() else ""
            memory_content = (agent_dir / "MEMORY.md").read_text(
                encoding="utf-8") if (agent_dir / "MEMORY.md").exists() else ""
            self._prompt_builder = PromptBuilder(
                PromptConfig(
                    identity_content=identity_content,
                    soul_content=soul_content,
                    user_content=user_content,
                    memory_content=memory_content,
                    workspace_dir=str(agent_dir),
                )
            )
        self._abort_event = asyncio.Event()
        self._base_system_prompt: Optional[str] = None
        self._memory_modified_this_turn: bool = False

        self._turns_since_review = 0
        self._guardrails = ToolGuardrails()
        self._approval = ApprovalManager()

    def interrupt(self) -> None:
        """Interrupt the current execution; the user can trigger this at any time."""
        self._abort_event.set()
        log.info("Agent interrupted")

    def resolve_approval(self, req_id: str, approved: bool, remember: bool = False) -> bool:
        """Resolve a pending approval request (called from server route)."""
        return self._approval.resolve(req_id, approved, remember)

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
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)

    def off(self, event: AgentEvent, handler: Callable) -> None:
        if event in self._event_handlers:
            self._event_handlers[event].remove(handler)

    async def _emit(self, event: AgentEvent, data: Any = None) -> None:
        if event in self._event_handlers:
            for handler in self._event_handlers[event]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event, data)
                    else:
                        handler(event, data)
                except Exception:
                    pass

    def _build_system_prompt(self, session_ctx: Any = None) -> str:
        tool_schemas = self.tool_registry.get_schema() if self.tool_registry.tools else []
        available_skills = self._skill_service.list_skills()
        return self._prompt_builder.build(
            tools_schemas=tool_schemas,
            available_skills=available_skills,
        )

    async def _get_messages(self) -> list[LLMMessage]:
        session = self.session.get_current_session()

        if self._base_system_prompt is None:
            await self._refresh_memory_index()
            self._base_system_prompt = self._build_system_prompt(session)

        messages = [LLMMessage(
            role="system", content=self._base_system_prompt)]

        db_messages = await self.session.get_messages()
        for msg in db_messages:
            m = LLMMessage(role=msg.role, content=msg.content)
            if msg.tool_calls:
                m.tool_calls = msg.tool_calls
            if msg.tool_call_id:
                m.tool_call_id = msg.tool_call_id
            if msg.images:
                m.images = msg.images
            if msg.reasoning_content:
                m.reasoning_content = msg.reasoning_content
            messages.append(m)
        return messages

    def _parse_tool_args(self, args_str: str) -> dict:
        if isinstance(args_str, dict):
            return args_str
        try:
            return json.loads(args_str)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Invalid JSON in tool call arguments: {args_str!r}\n"
                f"Parse error: {e}"
            )

    async def _execute_tool(self, tool_call: ToolCall, req_id: str = "") -> ToolResult:
        tool_name = tool_call.name if hasattr(
            tool_call, 'name') else str(tool_call)
        log.info(f"Executing tool: {tool_name}")
        tool_obj = self.tool_registry.get(tool_call.name)
        if not tool_obj:
            log.warning(f"Tool not found: {tool_call.name}")
            return ToolResult(success=False, content=f"Unknown tool: {tool_call.name}")
        try:
            args = self._parse_tool_args(tool_call.arguments)
            log.info(f"Tool {tool_name} args: {args}")
            if tool_name == "shell":
                args["_approval_manager"] = self._approval
                args["_agent_event_emitter"] = self._emit_approval
                args["_skip_wait"] = True
            result = await tool_obj.func(**args)
            log.info(
                f"Tool {tool_name} result: {result.content[:100] if result.content else 'empty'}...")
            guardrail_action = self._guardrails.observe(
                tool_name, args, result.success)
            if guardrail_action == GuardrailAction.HALT:
                log.warning(
                    "Guardrails halted tool loop after %s with %s", tool_name, args)
                return ToolResult(
                    success=False,
                    content="You seem to be repeating the same action. Try a different approach.",
                )
            return result
        except Exception as e:
            log.error(f"Tool {tool_name} error: {e}")
            self._guardrails.observe(tool_name, {}, False)
            return ToolResult(success=False, content=f"Tool error: {e}")

    async def _emit_approval(self, data: dict) -> None:
        await self._emit(AgentEvent.APPROVAL_REQUIRED, data)

    async def _execute_tool_with_abort(self, tc, req_id: str = "") -> Optional[ToolResult]:
        tool_task = asyncio.create_task(
            self._execute_tool(tc, req_id=req_id),
            name=f"tool_{tc.name}",
        )
        abort_task = asyncio.create_task(
            self._abort_event.wait(),
            name="abort_watcher",
        )

        done, pending = await asyncio.wait(
            [tool_task, abort_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        if abort_task in done:
            log.info("Tool %s aborted", tc.name if hasattr(tc, "name") else tc)
            return None

        try:
            return tool_task.result()
        except Exception as e:
            return ToolResult(success=False, content=f"Tool error: {e}")

    async def _run_turn(
        self,
        turn_count: int,
        tool_schemas: Any,
        group_id: Optional[str] = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        stop_payload = await self._wait_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return

        messages = await self._get_messages()

        accumulated_content = ""
        accumulated_reasoning = ""
        accumulated_tool_calls: dict[str, Any] = {}
        final_done_content = ""
        _text_started = False
        _reasoning_started = False
        _reasoning_started_at = None
        reasoning_elapsed_ms = None

        reasoning_timeout = get_reasoning_timeout(
            self.config.model, default=120)
        log.info(
            f"[Turn {turn_count}] Calling model={self.config.model}, tools={len(tool_schemas) if tool_schemas else 0}, timeout={reasoning_timeout}")
        generator_closing = False
        try:
            async for chunk in self.llm.chat_stream(
                messages=messages,
                model=self.config.model,
                tools=tool_schemas,
                abort_event=self._abort_event,
                timeout=reasoning_timeout,
            ):
                stop_payload = await self._wait_if_aborted()
                if stop_payload:
                    yield AgentEvent.DONE, stop_payload
                    return

                if hasattr(chunk, 'type'):
                    if chunk.type == "reasoning_delta":
                        if not _reasoning_started:
                            _reasoning_started = True
                            _reasoning_started_at = time.monotonic()
                            await self._emit(AgentEvent.REASONING_START)
                            yield AgentEvent.REASONING_START, None
                        accumulated_reasoning += chunk.content
                        yield AgentEvent.REASONING_DELTA, chunk.content
                    elif chunk.type == "text_delta":
                        if not _text_started:
                            _text_started = True
                            if accumulated_reasoning:
                                reasoning_elapsed_ms = int(
                                    (time.monotonic() - _reasoning_started_at) * 1000) if _reasoning_started_at else None
                                await self._emit(AgentEvent.REASONING_END)
                                yield AgentEvent.REASONING_END, reasoning_elapsed_ms
                            await self._emit(AgentEvent.TEXT_START)
                            yield AgentEvent.TEXT_START, None
                        cleaned = _scrubber.feed(chunk.content)
                        accumulated_content += chunk.content
                        if cleaned:
                            yield AgentEvent.TEXT_DELTA, cleaned
                    elif chunk.type == "done":
                        if getattr(chunk, "aborted", False):
                            yield AgentEvent.DONE, _done_payload("stopped", accumulated_content)
                            return
                        final_done_content = getattr(
                            chunk, "content", "") or final_done_content
                    elif chunk.type == "error":
                        yield AgentEvent.ERROR, _error_payload("llm_error", chunk.message)
                        return
                    elif chunk.type == "tool_call":
                        chunk_id = getattr(chunk, "id", None) or getattr(
                            chunk, "name", "")
                        if chunk_id:
                            accumulated_tool_calls[str(
                                chunk_id)] = chunk

                if hasattr(chunk, 'tool_calls') and chunk.tool_calls:
                    for tc in chunk.tool_calls:
                        tc_id = getattr(tc, "id", None) or getattr(
                            tc, "name", "")
                        if tc_id:
                            accumulated_tool_calls[str(tc_id)] = tc
        except GeneratorExit:
            generator_closing = True
            raise
        except Exception as e:
            log.error(f"[Turn {turn_count}] LLM call failed: {e}")
            yield AgentEvent.ERROR, _error_payload("llm_error", str(e))
            return
        finally:
            flushed = _scrubber.flush()
            if flushed:
                accumulated_content += flushed
            if accumulated_reasoning and not _text_started:
                reasoning_elapsed_ms = int(
                    (time.monotonic() - _reasoning_started_at) * 1000) if _reasoning_started_at else None
                await self._emit(AgentEvent.REASONING_END)
                if not generator_closing:
                    yield AgentEvent.REASONING_END, reasoning_elapsed_ms
            if _text_started:
                await self._emit(AgentEvent.TEXT_END, accumulated_content)
                if not generator_closing:
                    yield AgentEvent.TEXT_END, accumulated_content
        stop_payload = await self._wait_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return
        log.info(
            f"[Turn {turn_count}] After LLM loop: accumulated_content={len(accumulated_content)}, tool_calls={len(accumulated_tool_calls)}")

        final_content = accumulated_content or final_done_content
        final_tool_calls = [
            tc for tc in accumulated_tool_calls.values()
            if hasattr(tc, 'name') and tc.name
        ]

        valid_tool_calls = []
        for tc in final_tool_calls:
            args_str = tc.arguments if hasattr(tc, 'arguments') else "{}"
            if isinstance(args_str, str):
                try:
                    json.loads(args_str)
                    valid_tool_calls.append(tc)
                except json.JSONDecodeError:
                    log.warning(
                        f"[Turn {turn_count}] Skipping tool call {tc.name} "
                        f"with invalid JSON arguments: {args_str!r}"
                    )
            else:
                valid_tool_calls.append(tc)
        final_tool_calls = valid_tool_calls

        if final_tool_calls:
            for tc in final_tool_calls:
                tc_name = tc.name if hasattr(tc, 'name') else str(tc)
                tc_args = tc.arguments if hasattr(
                    tc, 'arguments') else "{}"
                log.info(
                    f"[Turn {turn_count}] Calling tool: {tc_name}({tc_args})")

            await self.session.add_message(
                role="assistant",
                content=final_content,
                tool_calls=[tc.model_dump() if hasattr(
                    tc, 'model_dump') else tc for tc in final_tool_calls],
                reasoning_content=accumulated_reasoning or None,
                group_id=group_id,
                reasoning_elapsed_ms=reasoning_elapsed_ms,
            )
            for tc in final_tool_calls:
                stop_payload = await self._wait_if_aborted()
                if stop_payload:
                    yield AgentEvent.DONE, stop_payload
                    return
                await self._emit(AgentEvent.TOOL_CALL, tc)
                yield AgentEvent.TOOL_CALL, tc
                stop_payload = await self._wait_if_aborted()
                if stop_payload:
                    yield AgentEvent.DONE, stop_payload
                    return

                req_id = ""
                tc_name = tc.name if hasattr(tc, 'name') else str(tc)
                if tc_name == "shell":
                    try:
                        tc_args = self._parse_tool_args(
                            tc.arguments if hasattr(tc, 'arguments') else "{}")
                        cmd = tc_args.get("command", "")
                        desc = tc_args.get("description", "") or cmd[:80]

                        blocked, hdesc = is_hardline(cmd)
                        if blocked:
                            log.info(
                                "Hardline command rejected: %s (%s)", cmd, hdesc)
                            yield AgentEvent.DONE, _done_payload("stopped", hdesc)
                            return

                        dangerous, ddesc = is_dangerous(cmd)
                        if dangerous:
                            req_id = self._approval.pre_request(
                                cmd, desc, timeout=0)
                            if req_id:
                                yield AgentEvent.APPROVAL_REQUIRED, {
                                    "id": req_id,
                                    "type": "shell",
                                    "command": cmd,
                                    "description": desc,
                                }
                                async for tick in self._approval.wait_with_heartbeat(req_id):
                                    if tick is None:
                                        yield AgentEvent.APPROVAL_HEARTBEAT, None
                                    else:
                                        if not tick:
                                            yield AgentEvent.DONE, _done_payload("stopped", "Command rejected by user")
                                            return
                                        break
                        else:
                            req_id = ""
                    except Exception:
                        pass

                result = await self._execute_tool_with_abort(tc, req_id=req_id)
                if result is None:
                    yield AgentEvent.DONE, _done_payload("stopped", "Stopped by user")
                    return

                tool_name = tc.name if hasattr(tc, 'name') else str(tc)
                images = None
                content = result.content

                if tool_name in ("read_image", "browser_use"):
                    try:
                        data = json.loads(content)
                        images = data.get("images", [])
                        content = data.get("text", "")
                    except (json.JSONDecodeError, TypeError):
                        pass

                await self.session.add_message(
                    role="tool",
                    content=content,
                    tool_call_id=tc.id if hasattr(tc, 'id') else str(tc),
                    images=images,
                    group_id=group_id,
                )
                tool_call_id = tc.id if hasattr(tc, 'id') else str(tc)
                await self._emit(
                    AgentEvent.TOOL_RESULT,
                    {
                        "tool": tc.name if hasattr(tc, 'name') else str(tc),
                        "tool_call_id": tool_call_id,
                        "result": result,
                    },
                )
                yield AgentEvent.TOOL_RESULT, {
                    "tool": tc.name if hasattr(tc, 'name') else str(tc),
                    "tool_call_id": tool_call_id,
                    "result": result,
                }
                if not result.success:
                    tool_name = tc.name if hasattr(tc, 'name') else str(tc)
                    log.info(
                        f"[Turn {turn_count}] Tool failed and will be returned to model context: {tool_name}")
                    continue
                if result.requires_input:
                    log.info(f"[Turn {turn_count}] Paused for user input")
                    yield AgentEvent.DONE, _done_payload("requires_input", "User input required")
                    return

                tool_name = tc.name if hasattr(tc, 'name') else str(tc)
                if tool_name in ("save_memory", "delete_memory"):
                    self._memory_modified_this_turn = True
        else:
            await self.session.add_message(
                role="assistant",
                content=final_content,
                reasoning_content=accumulated_reasoning or None,
                group_id=group_id,
                reasoning_elapsed_ms=reasoning_elapsed_ms,
            )
            done_payload = _done_payload("completed", final_content)
            await self._emit(AgentEvent.DONE, done_payload)
            log.info(f"[Turn {turn_count}] Completed without tool calls")
            yield AgentEvent.DONE, done_payload
            return

    async def chat_stream(
        self,
        user_input: str,
        session_id: str | None = None,
        attachments: list[dict] | None = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        self._abort_event.clear()

        if session_id:
            loaded = await self.session.load_session(session_id)
            if not loaded:
                await self.session.create_session(
                    persist=True,
                    first_message=user_input,
                )
        else:
            await self.session.create_session(
                persist=True,
                first_message=user_input,
            )

        current_session = self.session.get_current_session()
        session_id = current_session.id if current_session else ""

        yield AgentEvent.SESSION, session_id
        await self._emit(AgentEvent.START, user_input)
        yield AgentEvent.START, user_input

        image_data: list[str] = []
        message_text = user_input
        if attachments:
            for att in attachments:
                if att.get("type") == "image":
                    for part in att.get("content", []):
                        if part.get("type") == "image":
                            img_url = part.get("image", "")
                            if img_url.startswith("data:"):
                                _, base64_data = img_url.split(",", 1)
                                image_data.append(base64_data)
                elif att.get("type") == "document":
                    for part in att.get("content", []):
                        if part.get("type") == "text":
                            message_text = part.get(
                                "text", "") + "\n\n" + message_text
        self._last_user_input = message_text
        await self.session.add_message(
            role="user",
            content=message_text,
            images=image_data if image_data else None,
        )

        tool_schemas = self.tool_registry.get_schema() if self.tool_registry.tools else None

        db = await ensure_db()
        compaction_plan = await prepare_compaction(
            session_id=current_session.id if current_session else None,
            message_count=len(await self.session.get_messages()),
            turn_count=current_session.turn_count if current_session else 0,
            last_compacted_at=current_session.compacted_at if current_session else None,
            db=db,
            model=self.config.model,
            provider=self.config.provider,
        )
        if compaction_plan.needs_compaction:
            compaction_payload = {
                "message_count": len(compaction_plan.messages),
                "token_count": compaction_plan.token_count,
            }
            await self._emit(AgentEvent.COMPACTION_START, compaction_payload)
            yield AgentEvent.COMPACTION_START, compaction_payload
            await run_compaction_plan(
                compaction_plan,
                db=db,
                llm=self.llm,
                model=self.config.model,
                provider=self.config.provider,
            )
            current_session.compacted_at = int(
                datetime.now().timestamp() * 1000)
            await self._emit(AgentEvent.COMPACTION_END, compaction_payload)
            yield AgentEvent.COMPACTION_END, compaction_payload

        run_group_id = uuid.uuid4().hex
        turn_count = 0
        for _ in range(self.config.max_iterations):
            turn_count += 1
            await self._emit(AgentEvent.TURN_START, {"turn": turn_count})
            yield AgentEvent.TURN_START, {"turn": turn_count}

            done_payload = None
            async for event, data in self._run_turn(turn_count, tool_schemas, group_id=run_group_id):
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
                    if self.config.memory_review_interval > 0:
                        self._turns_since_review += 1
                        if self._turns_since_review >= self.config.memory_review_interval:
                            self._turns_since_review = 0
                            asyncio.create_task(
                                self._background_memory_review()
                            )
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
        from nova import tools as tools_module
        for name in dir(tools_module):
            if name.startswith("_"):
                continue
            self.tool_registry.register_by_metadata(name)
        from nova.skills.tools import SkillTools
        self._skill_tools = SkillTools(self._skill_service)
        self.tool_registry.register(
            self._skill_tools.list_skills, name="list_skills")
        self.tool_registry.register(
            self._skill_tools.load_skill, name="load_skill")
        self.tool_registry.register(
            self._skill_tools.install_skill, name="install_skill")

        # Register delegate_to_agent tool if this is not a sub-agent
        if not self.is_sub_agent:
            from nova.tools.delegate import delegate_to_agent
            self.tool_registry.register(
                delegate_to_agent, name="delegate_to_agent")

        # Register MCP remote tools
        if not self.is_sub_agent:
            try:
                mcp = MCPManager.get_shared()
                await mcp.ensure_initialized()
                mcp.register_tools(self.tool_registry)
            except Exception:
                log.exception("Failed to initialize MCP servers")

    async def _refresh_memory_index(self) -> None:
        """Build the memory index from DB for system prompt inclusion.

        Queries user-scoped memories and stores a compact listing in
        PromptConfig.memory_index.  This is called once per session (when
        _base_system_prompt is None) and again after save/delete memory
        invalidates the cache.
        """
        try:
            from nova.memory.context import build_memory_index_for_system
            self._prompt_builder.config.memory_index = (
                await build_memory_index_for_system()
            )
        except Exception as e:
            log.warning("Failed to refresh memory index: %s", e)

    async def _background_memory_review(self) -> None:
        try:
            messages = await self.session.get_messages(last_n=40)
            if len(messages) < 4:
                return

            from nova.memory.models import MemoryWriteRequest
            from nova.memory.service import MemoryService

            lines = []
            for m in messages[-30:]:
                role = getattr(m, "role", "?")
                content = getattr(m, "content", "") or ""
                if role == "tool":
                    content = content[:200] if len(content) > 200 else content
                if content:
                    lines.append(f"[{role}]: {content}")

            prompt = (
                "Review the recent conversation and extract durable facts "
                "worth remembering for future sessions.\n\n"
                "Focus on:\n"
                "- User preferences, habits, or communication style\n"
                "- Project architecture decisions or technology choices\n"
                "- Environment facts (paths, tools, configurations)\n"
                "- Recurring patterns or workflows\n\n"
                "Return a JSON array. Each entry must have:\n"
                "- key: short unique identifier (snake_case)\n"
                "- content: the full fact text\n"
                "- summary: 1-line summary\n"
                "- scope: \"user\" or \"project\" or \"session\"\n"
                "- memory_type: \"fact\" or \"preference\" or \"decision\" or \"context\"\n"
                "- tags: list of keywords\n\n"
                "Conversation:\n" + "\n".join(lines[-30:]) +
                "\n\nReturn ONLY valid JSON array. If nothing worth saving, "
                "return []."
            )

            result = await self.llm.chat(
                messages=[LLMMessage(role="user", content=prompt)],
                model=self.config.model,
            )
            facts = self._parse_review_facts(result.content)
            if not facts:
                return

            service = MemoryService()
            saved = 0
            for fact in facts:
                try:
                    _, created = await service.save(MemoryWriteRequest(
                        key=fact.get("key", "auto-review"),
                        content=fact.get("content", ""),
                        summary=fact.get("summary", ""),
                        scope=fact.get("scope", "user"),
                        memory_type=fact.get("memory_type", "fact"),
                        tags=fact.get("tags", []),
                    ))
                    if created:
                        saved += 1
                except Exception as e:
                    log.debug("Failed to save reviewed fact: %s", e)
            if saved:
                log.info("Memory review saved %d new fact(s)", saved)
        except Exception as e:
            log.warning("Background memory review failed: %s", e)

    @staticmethod
    def _parse_review_facts(content: str) -> list[dict]:
        text = content.strip()
        if not text:
            return []
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(text[start:end+1])
                except json.JSONDecodeError:
                    return []
            else:
                return []
        if not isinstance(parsed, list):
            return []
        return parsed

    def add_sub_agent(self, sub_agent: "Agent") -> None:
        """Add a sub-agent to this agent's list of sub-agents."""
        sub_agent.parent_agent = self
        sub_agent.is_sub_agent = True
        self._sub_agents.append(sub_agent)

    def get_sub_agents(self) -> list["Agent"]:
        """Get all sub-agents of this agent."""
        return self._sub_agents.copy()

    def get_parent_agent(self) -> Optional["Agent"]:
        """Get the parent agent (if this is a sub-agent)."""
        return self.parent_agent

    async def get_child_agents(self) -> list[dict]:
        """Get all child agents of this agent from database."""
        from nova.db.database import ensure_db
        db = await ensure_db()
        child_keys = await db.get_agent_children(self.agent_key)
        children = []
        for key in child_keys:
            agent = await db.get_agent(key)
            if agent:
                children.append(agent)
        return children

    async def get_parent_agents(self) -> list[dict]:
        """Get all parent agents of this agent from database."""
        from nova.db.database import ensure_db
        db = await ensure_db()
        parent_keys = await db.get_agent_parents(self.agent_key)
        parents = []
        for key in parent_keys:
            agent = await db.get_agent(key)
            if agent:
                parents.append(agent)
        return parents

    async def get_parent_agent_config(self) -> Optional[dict]:
        """Get the first parent agent configuration from database."""
        from nova.db.database import ensure_db
        db = await ensure_db()
        parent_keys = await db.get_agent_parents(self.agent_key)
        if parent_keys:
            return await db.get_agent(parent_keys[0])
        return None
