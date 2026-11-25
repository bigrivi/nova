"""Standalone tool execution keeps every announced call terminal."""

from __future__ import annotations

import asyncio

import pytest

from novakit.agent.tool_invoker import ToolInvoker
from novakit.events import AgentEvent, AgentEventFrame
from novakit.llm import FakerLLMProvider, ToolCall, ToolResult
from novakit.session import InMemorySession
from novakit.tools import PreExecutionCheck, ToolRegistry
from novakit.tools.behavior import DefaultToolBehavior


class _ApprovalBehavior(DefaultToolBehavior):
    async def before_execute(self, args: dict, ctx: object) -> PreExecutionCheck:
        return PreExecutionCheck(approval_request={"id": "req-1"})


@pytest.mark.asyncio
async def test_missing_approval_manager_refuses_without_running_tool() -> None:
    session = InMemorySession()
    await session.create_session()
    registry = ToolRegistry()
    executed = False

    async def guarded() -> ToolResult:
        nonlocal executed
        executed = True
        return ToolResult(content="ran")

    registry.register(guarded, name="guarded")
    registry.set_behavior("guarded", _ApprovalBehavior())
    emitted: list[AgentEventFrame] = []

    async def emit(event: AgentEvent, data: object = None) -> None:
        emitted.append((event, data))

    async def stop_if_aborted() -> dict | None:
        return None

    invoker = ToolInvoker(
        registry=registry,
        session=session,
        approval=None,
        guardrails=None,
        llm=FakerLLMProvider(seed=1),
        model="fake",
        provider="test",
        abort_event=asyncio.Event(),
        emit=emit,
        emit_approval=emit,
        stop_if_aborted=stop_if_aborted,
    )
    frames = [
        frame
        async for frame in invoker.run(
            [ToolCall(id="call-1", name="guarded", arguments="{}")]
        )
    ]

    assert executed is False
    assert [event for event, _ in frames] == [
        AgentEvent.TOOL_CALL,
        AgentEvent.APPROVAL_REQUIRED,
        AgentEvent.APPROVAL_RESULT,
        AgentEvent.TOOL_RESULT,
    ]
    assert frames[-1][1]["result"].denied is True
    assert (await session.get_messages())[-1].role == "tool"
