"""Standalone novakit.Agent runs full turns without Nova or filesystem state."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

import pytest

from novakit import Agent, AgentConfig, AgentOptions
from novakit.events import AgentEvent, AgentEventFrame
from novakit.llm import (
    ChatStreamEvent,
    Done,
    LLMProvider,
    TextDelta,
    ToolCall,
    ToolResult,
)
from novakit.session import InMemorySession
from novakit.tools import (
    DefaultToolBehavior,
    PreExecutionCheck,
    ToolRegistry,
    TurnContext,
    tool,
)


class ScriptedProvider(LLMProvider):
    def __init__(self, scripts: list[list[object]]) -> None:
        self._scripts = scripts
        self._index = 0
        self.seen_messages: list[list] = []

    async def chat(
        self,
        messages: list,
        model: str = "m",
        stream: bool = False,
        tools: list[dict] | None = None,
        **kwargs: object,
    ) -> Done:
        return Done(content="summary")

    async def chat_stream(
        self,
        messages: list,
        model: str = "m",
        tools: list[dict] | None = None,
        **kwargs: object,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        self.seen_messages.append(messages)
        script = self._scripts[min(self._index, len(self._scripts) - 1)]
        self._index += 1
        for item in script:
            await asyncio.sleep(0)
            yield item

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


async def collect(agent: Agent, text: str, **kwargs: object) -> list[AgentEventFrame]:
    return [frame async for frame in agent.chat_stream(text, **kwargs)]


def test_constructor_delegates_all_state_to_runtime_initializer() -> None:
    core_path = (
        Path(__file__).resolve().parents[1] / "src" / "novakit" / "agent" / "core.py"
    )
    tree = ast.parse(core_path.read_text(encoding="utf-8"))
    agent_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Agent"
    )
    methods = {
        node.name: node
        for node in agent_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def assigned_fields(method: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        return {
            node.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and isinstance(node.ctx, ast.Store)
        }

    assert assigned_fields(methods["__init__"]) == set()
    assert assigned_fields(methods["_initialize_runtime"]) == {
        "config",
        "agent_key",
        "llm",
        "session",
        "tool_registry",
        "_events",
        "parent_agent",
        "is_sub_agent",
        "depth",
        "allowed_tools",
        "state",
        "_background_tasks",
        "messaging",
        "background",
        "session_service",
        "_compactor",
        "_approval",
        "_guardrails",
        "_begin_turn",
        "_abort_event",
    }


@dataclass
class MinimalConfig:
    model: str = "test"
    provider: str = "test"
    max_iterations: int = 2
    reasoning_effort: str | None = None


class _ApprovalBehavior(DefaultToolBehavior):
    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        assert ctx.approval_manager is not None
        request_id = ctx.approval_manager.pre_request(
            "guarded", session_id=ctx.session_id
        )
        return PreExecutionCheck(approval_request={"id": request_id})


@pytest.mark.asyncio
async def test_agent_accepts_narrow_core_config() -> None:
    agent = Agent(
        MinimalConfig(),
        ScriptedProvider([[TextDelta(content="ok")]]),
    )

    frames = await collect(agent, "hello")

    assert frames[-1][1]["content"] == "ok"


@pytest.mark.asyncio
async def test_plain_turn_uses_memory_session_and_static_prompt() -> None:
    provider = ScriptedProvider([[TextDelta(content="hello")]])
    agent = Agent(
        AgentConfig(model="test", max_iterations=2),
        provider,
        options=AgentOptions(system_prompt="Be concise."),
    )

    frames = await collect(agent, "hi")

    assert isinstance(agent.session, InMemorySession)
    assert frames[0][0] is AgentEvent.SESSION
    assert frames[-1][0] is AgentEvent.DONE
    assert frames[-1][1]["content"] == "hello"
    messages = await agent.session.get_messages()
    assert [(message.role, message.content) for message in messages] == [
        ("user", "hi"),
        ("assistant", "hello"),
    ]
    assert provider.seen_messages[0][0].content == "Be concise."


@pytest.mark.asyncio
async def test_tool_turn_persists_pair_and_continues() -> None:
    provider = ScriptedProvider(
        [
            [ToolCall(id="call-1", name="echo", arguments='{"text":"hi"}')],
            [TextDelta(content="done")],
        ]
    )
    registry = ToolRegistry()

    @tool(
        name="echo",
        parameters={
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    async def echo(text: str) -> ToolResult:
        return ToolResult(content=f"echo:{text}")

    registry.register(echo, name="echo")
    agent = Agent(
        AgentConfig(model="test", max_iterations=3),
        provider,
        options=AgentOptions(tools=registry),
    )

    frames = await collect(agent, "go")

    assert any(event is AgentEvent.TOOL_CALL for event, _ in frames)
    assert any(event is AgentEvent.TOOL_RESULT for event, _ in frames)
    assert [
        (message.role, message.content)
        for message in await agent.session.get_messages()
    ] == [
        ("user", "go"),
        ("assistant", ""),
        ("tool", "echo:hi"),
        ("assistant", "done"),
    ]


@pytest.mark.asyncio
async def test_default_agent_can_resolve_tool_approval() -> None:
    provider = ScriptedProvider(
        [
            [ToolCall(id="call-1", name="guarded", arguments="{}")],
            [TextDelta(content="done")],
        ]
    )
    registry = ToolRegistry()
    executed = False

    async def guarded() -> ToolResult:
        nonlocal executed
        executed = True
        return ToolResult(content="ran")

    registry.register(guarded, name="guarded")
    registry.set_behavior("guarded", _ApprovalBehavior())
    agent = Agent(
        AgentConfig(model="test", max_iterations=3),
        provider,
        options=AgentOptions(tools=registry),
    )
    frames: list[AgentEventFrame] = []

    async for event, data in agent.chat_stream("go"):
        frames.append((event, data))
        if event is AgentEvent.APPROVAL_REQUIRED:
            assert agent.resolve_approval(data["id"], True) is True

    assert executed is True
    assert frames[-1][1]["content"] == "done"
    assert any(event is AgentEvent.TOOL_RESULT for event, _ in frames)


@pytest.mark.asyncio
async def test_default_agent_does_not_create_user_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    nova_home = tmp_path / "nova-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("NOVA_HOME", str(nova_home))
    agent = Agent(
        AgentConfig(model="test"),
        ScriptedProvider([[TextDelta(content="ok")]]),
    )

    await collect(agent, "hello")

    assert not home.exists()
    assert not nova_home.exists()


@pytest.mark.asyncio
async def test_reusing_session_keeps_history() -> None:
    provider = ScriptedProvider(
        [[TextDelta(content="one")], [TextDelta(content="two")]]
    )
    agent = Agent(AgentConfig(model="test"), provider)
    first = await collect(agent, "first")
    session_id = first[0][1]

    second = await collect(agent, "second", session_id=session_id)

    assert second[0][1] == session_id
    assert [message.content for message in await agent.session.get_messages()] == [
        "first",
        "one",
        "second",
        "two",
    ]


@pytest.mark.asyncio
async def test_missing_provider_fails_clearly() -> None:
    agent = Agent(AgentConfig(model="test"), None)

    with pytest.raises(RuntimeError, match="no LLM provider"):
        await collect(agent, "hello")
