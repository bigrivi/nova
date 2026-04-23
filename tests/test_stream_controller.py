from __future__ import annotations

from dataclasses import dataclass

import pytest

from nova.agent import AgentEvent
from nova.cli.stream_controller import StreamController, StreamControlProtocol, StreamRenderProtocol
from nova.llm.provider import ToolResult


class _FakeMonitor:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _FakeSpinner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []

    def stop(self) -> None:
        self.calls.append(("stop", None))

    def start_llm(self) -> None:
        self.calls.append(("start_llm", None))

    def start_tool(self, tool_name: str) -> None:
        self.calls.append(("start_tool", tool_name))


class _FakeAgent:
    def __init__(self, events: list[tuple[AgentEvent, object]]) -> None:
        self._events = events
        self.calls: list[tuple[str, str | None]] = []

    async def chat_stream(self, user_input: str, session_id: str | None = None):
        self.calls.append((user_input, session_id))
        for item in self._events:
            yield item


@dataclass
class _FakeRender(StreamRenderProtocol):
    reset_count: int = 0
    chunks: list[tuple[str, bool]] = None
    flush_count: int = 0
    tool_calls: list[tuple[object, str]] = None
    tool_results: list[tuple[object, object]] = None
    infos: list[str] = None
    errors: list[str] = None
    monitor: _FakeMonitor = None
    stop_requests: int = 0

    def __post_init__(self) -> None:
        self.chunks = []
        self.tool_calls = []
        self.tool_results = []
        self.infos = []
        self.errors = []

    def reset_stream_state(self) -> None:
        self.reset_count += 1

    def write_text_chunk(self, chunk: str, *, is_first: bool) -> None:
        self.chunks.append((chunk, is_first))

    def flush(self) -> None:
        self.flush_count += 1

    def print_tool_call(self, tool_call: object, tool_name: str) -> None:
        self.tool_calls.append((tool_call, tool_name))

    def print_tool_result(self, tool_name: object, content: object) -> None:
        self.tool_results.append((tool_name, content))

    def show_info(self, text: str) -> None:
        self.infos.append(text)

    def show_error(self, text: str) -> None:
        self.errors.append(text)


@dataclass
class _FakeControl(StreamControlProtocol):
    session_id: str | None = None
    pending_input: dict | None = None
    monitor: _FakeMonitor = None
    stop_requests: int = 0

    def __post_init__(self) -> None:
        self.monitor = _FakeMonitor()

    def get_session_id(self) -> str | None:
        return self.session_id

    def set_session_id(self, session_id: str | None) -> None:
        self.session_id = session_id

    def set_pending_input(self, payload: dict) -> None:
        self.pending_input = payload

    def create_cancel_monitor(self, on_escape):
        return self.monitor

    def request_stop(self) -> None:
        self.stop_requests += 1


@pytest.mark.asyncio
async def test_stream_controller_writes_text_delta_and_stops_spinner():
    agent = _FakeAgent([(AgentEvent.TEXT_DELTA, "hello")])
    spinner = _FakeSpinner()
    render = _FakeRender()
    control = _FakeControl(session_id="sess-1")
    controller = StreamController(agent=agent, spinner=spinner, render=render, control=control)

    await controller.run("hi")

    assert agent.calls == [("hi", "sess-1")]
    assert render.reset_count == 1
    assert render.chunks == [("hello", True)]
    assert ("stop", None) in spinner.calls
    assert control.monitor.started is True
    assert control.monitor.stopped is True


@pytest.mark.asyncio
async def test_stream_controller_records_tool_call_and_starts_tool_spinner():
    tool_call = type("ToolCallStub", (), {"name": "read"})()
    agent = _FakeAgent([(AgentEvent.TOOL_CALL, tool_call)])
    spinner = _FakeSpinner()
    render = _FakeRender()
    control = _FakeControl()
    controller = StreamController(agent=agent, spinner=spinner, render=render, control=control)

    await controller.run("hi")

    assert render.tool_calls == [(tool_call, "read")]
    assert ("start_tool", "read") in spinner.calls


@pytest.mark.asyncio
async def test_stream_controller_sets_pending_input_for_requires_input():
    result = ToolResult(success=True, requires_input=True, content="payload")
    agent = _FakeAgent([(AgentEvent.TOOL_RESULT, {"tool": "ask_user", "result": result})])
    spinner = _FakeSpinner()
    render = _FakeRender()
    control = _FakeControl()
    controller = StreamController(agent=agent, spinner=spinner, render=render, control=control)

    await controller.run("hi")

    assert control.pending_input == {"content": "payload"}
    assert render.tool_results == [("ask_user", "payload")]


@pytest.mark.asyncio
async def test_stream_controller_done_with_tool_content_shows_info():
    tool_call = type("ToolCallStub", (), {"name": "edit"})()
    agent = _FakeAgent(
        [
            (AgentEvent.TOOL_CALL, tool_call),
            (AgentEvent.DONE, {"reason": "completed", "content": "Finished"}),
        ]
    )
    spinner = _FakeSpinner()
    render = _FakeRender()
    control = _FakeControl()
    controller = StreamController(agent=agent, spinner=spinner, render=render, control=control)

    await controller.run("hi")

    assert render.infos == ["Finished"]


@pytest.mark.asyncio
async def test_stream_controller_done_error_like_content_shows_error():
    agent = _FakeAgent([(AgentEvent.DONE, "Error: HTTP 400")])
    spinner = _FakeSpinner()
    render = _FakeRender()
    control = _FakeControl()
    controller = StreamController(agent=agent, spinner=spinner, render=render, control=control)

    await controller.run("hi")

    assert render.errors == ["Error: HTTP 400"]


@pytest.mark.asyncio
async def test_stream_controller_done_tool_failed_shows_error():
    agent = _FakeAgent([(AgentEvent.DONE, {"reason": "tool_failed", "content": "edit failed"})])
    spinner = _FakeSpinner()
    render = _FakeRender()
    control = _FakeControl()
    controller = StreamController(agent=agent, spinner=spinner, render=render, control=control)

    await controller.run("hi")

    assert render.errors == ["edit failed"]


@pytest.mark.asyncio
async def test_stream_controller_done_requires_input_is_terminal():
    agent = _FakeAgent([(AgentEvent.DONE, {"reason": "requires_input", "content": "User input required"})])
    spinner = _FakeSpinner()
    render = _FakeRender()
    control = _FakeControl()
    controller = StreamController(agent=agent, spinner=spinner, render=render, control=control)

    await controller.run("hi")

    assert render.errors == []
    assert render.infos == []
    assert control.monitor.stopped is True


@pytest.mark.asyncio
async def test_stream_controller_empty_done_without_tool_calls_is_terminal():
    agent = _FakeAgent(
        [
            (AgentEvent.DONE, {"reason": "completed", "content": ""}),
            (AgentEvent.TEXT_DELTA, "should not be consumed"),
        ]
    )
    spinner = _FakeSpinner()
    render = _FakeRender()
    control = _FakeControl()
    controller = StreamController(agent=agent, spinner=spinner, render=render, control=control)

    await controller.run("hi")

    assert render.chunks == []
    assert control.monitor.stopped is True


@pytest.mark.asyncio
async def test_stream_controller_error_event_shows_error():
    agent = _FakeAgent([(AgentEvent.ERROR, {"reason": "provider", "message": "boom"})])
    spinner = _FakeSpinner()
    render = _FakeRender()
    control = _FakeControl()
    controller = StreamController(agent=agent, spinner=spinner, render=render, control=control)

    await controller.run("hi")

    assert render.errors == ["boom"]
