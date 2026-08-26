from __future__ import annotations

import asyncio
import json

import pytest

from nova.llm.faker import FakerLLMProvider
from nova.llm.provider import Done, Error, LLMProvider, ReasoningDelta, TextDelta, ToolCall, ToolResult
from nova import Agent, AgentConfig
from nova.agent.core import AgentEvent
from nova.db.in_memory_repository import InMemoryRepository
from nova.session.manager import SessionManager


@pytest.mark.asyncio
async def test_faker_provider_matches_llm_protocol_and_is_deterministic():
    provider = FakerLLMProvider(seed=7, reasoning_probability=0)
    messages = [{"role": "user", "content": "Explain this project."}]

    first = await provider.chat(messages, model="fake")
    second = await provider.chat(messages, model="fake")

    assert isinstance(provider, LLMProvider)
    assert isinstance(first, Done)
    assert first.content == second.content
    assert first.content != "FakerLLM response: Explain this project."


@pytest.mark.asyncio
async def test_faker_provider_returns_natural_markdown_for_greeting():
    provider = FakerLLMProvider(seed=7, reasoning_probability=0)

    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert isinstance(response, Done)
    assert response.content != "FakerLLM response: hello"
    assert response.content


@pytest.mark.asyncio
async def test_faker_stream_emits_text_and_done():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0)

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "Hello"}], model="fake"
        )
    ]

    assert isinstance(events[-1], Done)
    assert any(isinstance(event, TextDelta) for event in events)
    assert events[-1].content == "".join(
        event.content for event in events if isinstance(event, TextDelta)
    )


@pytest.mark.asyncio
async def test_faker_stream_can_emit_reasoning_before_text():
    provider = FakerLLMProvider(seed=1, reasoning_probability=1)

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "Hello"}], model="fake"
        )
    ]

    reasoning_deltas = [
        event for event in events if isinstance(event, ReasoningDelta)
    ]
    assert reasoning_deltas, "expected at least one ReasoningDelta"
    assert isinstance(events[0], ReasoningDelta)
    assert isinstance(events[-1], Done)
    assert len(reasoning_deltas) > 1, "reasoning should be streamed in multiple chunks"
    assert reasoning_deltas[0].content == reasoning_deltas[0].content.lstrip()
    assert "".join(event.content for event in reasoning_deltas)
    assert any(isinstance(event, TextDelta) for event in events)


@pytest.mark.asyncio
async def test_faker_stream_honors_abort_event():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0)
    abort_event = asyncio.Event()
    abort_event.set()

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "Hello"}],
            abort_event=abort_event,
        )
    ]

    assert isinstance(events[-1], Done)
    assert events[-1].aborted is True


@pytest.mark.asyncio
async def test_faker_stream_honors_abort_during_reasoning():
    provider = FakerLLMProvider(seed=1, reasoning_probability=1)
    abort_event = asyncio.Event()
    abort_event.set()

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "Hello"}],
            abort_event=abort_event,
        )
    ]

    assert isinstance(events[-1], Done)
    assert events[-1].aborted is True
    assert not any(isinstance(event, ReasoningDelta) for event in events)


@pytest.mark.asyncio
async def test_faker_provider_can_return_error_event():
    provider = FakerLLMProvider(seed=1, error_probability=1)

    response = await provider.chat([{"role": "user", "content": "Hello"}])
    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "Hello"}]
        )
    ]

    assert isinstance(response, Error)
    assert isinstance(events[0], Error)


@pytest.mark.asyncio
async def test_faker_provider_exposes_token_contract():
    provider = FakerLLMProvider(max_tokens=4096)

    assert await provider.count_tokens("12345678") == 2
    assert await provider.count_tokens("") == 0
    assert provider.get_max_tokens("fake") == 4096


@pytest.mark.asyncio
async def test_faker_provider_generates_schema_valid_tool_call_without_executing_it():
    provider = FakerLLMProvider(
        seed=4,
        reasoning_probability=0,
        tool_call_probability=1,
        continue_tool_probability=0,
        max_tool_calls_per_turn=1,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filePath": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["filePath"],
                },
            },
        }
    ]

    response = await provider.chat(
        [{"role": "user", "content": "inspect the project"}],
        tools=tools,
    )
    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "inspect the project"}],
            tools=tools,
        )
    ]

    assert isinstance(response, Done)
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "read"
    arguments = json.loads(response.tool_calls[0].arguments)
    assert "filePath" in arguments
    assert arguments["limit"] == 10
    assert any(isinstance(event, ToolCall) for event in events)
    assert isinstance(events[-1], Done)


@pytest.mark.asyncio
async def test_faker_tool_probability_remains_reachable_with_error_probability():
    provider = FakerLLMProvider(
        seed=1,
        reasoning_probability=0,
        error_probability=0.3,
        tool_call_probability=0.3,
    )
    tools = [{"function": {"name": "read", "parameters": {"type": "object"}}}]

    responses = [await provider.chat([{"role": "user", "content": str(i)}], tools=tools) for i in range(20)]

    assert any(isinstance(response, Done) and response.tool_calls for response in responses)


@pytest.mark.asyncio
async def test_faker_provider_can_emit_multiple_tool_calls_in_one_turn():
    provider = FakerLLMProvider(
        seed=4,
        reasoning_probability=0,
        tool_call_probability=1,
        max_tool_calls_per_turn=2,
    )
    tools = [
        {"function": {"name": "read", "parameters": {"type": "object"}}},
        {"function": {"name": "glob", "parameters": {"type": "object"}}},
    ]

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "inspect the project"}],
            tools=tools,
        )
    ]
    tool_calls = [event for event in events if isinstance(event, ToolCall)]

    assert len(tool_calls) == 2
    assert len({tool_call.id for tool_call in tool_calls}) == 2
    assert isinstance(events[-1], Done)
    assert len(events[-1].tool_calls) == 2


@pytest.mark.asyncio
async def test_faker_provider_can_call_tool_for_greeting_when_probability_allows():
    provider = FakerLLMProvider(
        seed=4,
        reasoning_probability=0,
        tool_call_probability=1,
        max_tool_calls_per_turn=1,
    )
    tools = [{"function": {"name": "list_skills", "parameters": {"type": "object"}}}]

    response = await provider.chat([{"role": "user", "content": "hello"}], tools=tools)

    assert isinstance(response, Done)
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "list_skills"


@pytest.mark.asyncio
async def test_faker_tool_call_honors_abort_event():
    provider = FakerLLMProvider(
        seed=4,
        reasoning_probability=0,
        tool_call_probability=1,
    )
    abort_event = asyncio.Event()
    abort_event.set()
    tools = [{"function": {"name": "read", "parameters": None}}]

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "inspect the project"}],
            tools=tools,
            abort_event=abort_event,
        )
    ]

    assert isinstance(events[-1], Done)
    assert events[-1].aborted is True
    assert not any(isinstance(event, ToolCall) for event in events)


@pytest.mark.asyncio
async def test_faker_provider_handles_null_tool_parameters():
    provider = FakerLLMProvider(
        seed=4,
        reasoning_probability=0,
        tool_call_probability=1,
    )
    tools = [{"function": {"name": "read", "parameters": None}}]

    response = await provider.chat(
        [{"role": "user", "content": "inspect the project"}],
        tools=tools,
    )

    assert isinstance(response, Done)
    assert json.loads(response.tool_calls[0].arguments) == {}


@pytest.mark.asyncio
async def test_faker_tool_call_uses_existing_agent_execution_loop(tmp_path):
    repository = InMemoryRepository()
    executed_arguments: list[dict] = []

    async def fake_read(filePath: str) -> ToolResult:
        executed_arguments.append({"filePath": filePath})
        return ToolResult(success=True, content="simulated file content")

    provider = FakerLLMProvider(
        seed=4,
        reasoning_probability=0,
        tool_call_probability=1,
    )
    session_manager = SessionManager(data_source=repository)
    agent = Agent(
        config=AgentConfig(model="fake", max_iterations=3),
        llm_provider=provider,
        session_manager=session_manager,
        data_source=repository,
        agent_dir=tmp_path / "agent",
    )
    agent.tool_registry.register_direct(
        name="read",
        description="Read a file",
        func=fake_read,
        params_schema={
            "type": "object",
            "properties": {"filePath": {"type": "string"}},
            "required": ["filePath"],
        },
    )

    events = [event async for event, _ in agent.chat_stream("inspect the project")]
    messages = await session_manager.get_messages()

    assert executed_arguments == [{"filePath": "README.md"}]
    assert AgentEvent.TOOL_CALL in events
    assert AgentEvent.TOOL_RESULT in events
    assert events[-1] == AgentEvent.DONE
    assert [message.role for message in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[2].content == "simulated file content"


@pytest.mark.asyncio
async def test_faker_provider_summarizes_tool_result_on_next_turn():
    provider = FakerLLMProvider(
        seed=4,
        reasoning_probability=0,
        tool_call_probability=1,
        continue_tool_probability=0,
    )
    tools = [{"function": {"name": "read", "parameters": {"type": "object"}}}]
    messages = [
        {"role": "user", "content": "inspect the project"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "README content"},
    ]

    events = [event async for event in provider.chat_stream(messages, tools=tools)]

    assert not any(isinstance(event, ToolCall) for event in events)
    assert isinstance(events[-1], Done)
    assert "README content" in events[-1].content


@pytest.mark.asyncio
async def test_faker_content_driven_tool_call_fires_regardless_of_probability():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0, tool_call_probability=0.0)
    tools = [
        {
            "function": {
                "name": "read",
                "parameters": {
                    "type": "object",
                    "properties": {"filePath": {"type": "string"}},
                    "required": ["filePath"],
                },
            }
        }
    ]

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "帮我看下 README.md 的文件内容"}],
            tools=tools,
        )
    ]
    tool_calls = [event for event in events if isinstance(event, ToolCall)]

    assert len(tool_calls) == 1
    assert tool_calls[0].name == "read"
    assert json.loads(tool_calls[0].arguments)["filePath"] == "README.md"


@pytest.mark.asyncio
async def test_faker_content_driven_can_trigger_multiple_tools():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0, tool_call_probability=0.0)
    tools = [
        {"function": {"name": "glob", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}}}},
        {"function": {"name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
    ]

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "先查找文件，然后运行命令"}],
            tools=tools,
        )
    ]
    names = [event.name for event in events if isinstance(event, ToolCall)]

    assert len(names) == 2
    assert set(names) == {"glob", "shell"}
    assert isinstance(events[-1], Done)
    assert len(events[-1].tool_calls) == 2


@pytest.mark.asyncio
async def test_faker_content_driven_skips_unavailable_tools():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0, tool_call_probability=0.0)
    tools = [{"function": {"name": "glob", "parameters": {"type": "object"}}}]

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "读取文件内容"}],
            tools=tools,
        )
    ]

    assert not any(isinstance(event, ToolCall) for event in events)
    assert isinstance(events[-1], Done)


@pytest.mark.asyncio
async def test_faker_content_driven_extracts_url_for_web_fetch():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0, tool_call_probability=0.0)
    tools = [
        {
            "function": {
                "name": "web_fetch",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            }
        }
    ]

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "帮我抓取网页 https://example.com/docs"}],
            tools=tools,
        )
    ]
    tool_calls = [event for event in events if isinstance(event, ToolCall)]

    assert len(tool_calls) == 1
    assert tool_calls[0].name == "web_fetch"
    assert json.loads(tool_calls[0].arguments)["url"] == "https://example.com/docs"


@pytest.mark.asyncio
async def test_faker_content_driven_does_not_refire_while_summarizing_tool_result():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0, tool_call_probability=0.0)
    tools = [{"function": {"name": "read", "parameters": {"type": "object"}}}]
    messages = [
        {"role": "user", "content": "帮我看下 README.md 的文件内容"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "README content"},
    ]

    events = [event async for event in provider.chat_stream(messages, tools=tools)]

    assert not any(isinstance(event, ToolCall) for event in events)
    assert isinstance(events[-1], Done)


@pytest.mark.asyncio
async def test_faker_content_driven_edit_carries_mock_diff_strings():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0, tool_call_probability=0.0)
    tools = [
        {
            "function": {
                "name": "edit",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filePath": {"type": "string"},
                        "oldString": {"type": "string"},
                        "newString": {"type": "string"},
                    },
                    "required": ["filePath", "oldString", "newString"],
                },
            }
        }
    ]

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "帮我修改文件 app.py"}],
            tools=tools,
        )
    ]
    tool_calls = [event for event in events if isinstance(event, ToolCall)]

    assert len(tool_calls) == 1
    assert tool_calls[0].name == "edit"
    args = json.loads(tool_calls[0].arguments)
    assert args["filePath"] == "app.py"
    assert args["oldString"] and args["newString"]
    assert args["oldString"] != args["newString"]


@pytest.mark.asyncio
async def test_faker_edit_mock_strings_track_file_extension():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0, tool_call_probability=0.0)
    tools = [
        {
            "function": {
                "name": "edit",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filePath": {"type": "string"},
                        "oldString": {"type": "string"},
                        "newString": {"type": "string"},
                    },
                    "required": ["filePath", "oldString", "newString"],
                },
            }
        }
    ]

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "帮我编辑文件 widget.tsx"}],
            tools=tools,
        )
    ]
    args = json.loads(next(e for e in events if isinstance(e, ToolCall)).arguments)

    assert args["filePath"] == "widget.tsx"
    assert "function greet" in args["oldString"]
    assert "`hi ${name}`" in args["newString"]


@pytest.mark.asyncio
async def test_faker_content_driven_todo_write_generates_realistic_list():
    provider = FakerLLMProvider(seed=1, reasoning_probability=0, tool_call_probability=0.0)
    tools = [
        {
            "function": {
                "name": "todo_write",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["pending", "in_progress", "completed", "cancelled"],
                                    },
                                    "priority": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                    },
                                },
                                "required": ["content", "status", "priority"],
                            },
                        },
                    },
                    "required": ["todos"],
                },
            }
        }
    ]

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "帮我列一个任务清单"}],
            tools=tools,
        )
    ]
    tool_calls = [event for event in events if isinstance(event, ToolCall)]

    assert len(tool_calls) == 1
    assert tool_calls[0].name == "todo_write"
    todos = json.loads(tool_calls[0].arguments)["todos"]

    assert len(todos) >= 3
    assert sum(1 for todo in todos if todo["status"] == "in_progress") == 1
    statuses = {todo["status"] for todo in todos}
    assert "completed" in statuses
    assert "pending" in statuses
    for todo in todos:
        assert todo["content"]
        assert todo["status"] in {"pending", "in_progress", "completed", "cancelled"}
        assert todo["priority"] in {"high", "medium", "low"}


@pytest.mark.asyncio
async def test_faker_stream_delay_invokes_sleep_between_chunks(monkeypatch):
    recorded: list[float] = []

    async def fake_sleep(duration: float) -> None:
        recorded.append(duration)

    monkeypatch.setattr("nova.llm.faker.asyncio.sleep", fake_sleep)
    provider = FakerLLMProvider(seed=1, reasoning_probability=1, stream_delay=0.05)

    events = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "Hello"}]
        )
    ]

    assert any(isinstance(event, ReasoningDelta) for event in events)
    assert recorded, "expected asyncio.sleep to be called when stream_delay > 0"
    assert all(duration == 0.05 for duration in recorded)


@pytest.mark.asyncio
async def test_faker_no_stream_delay_skips_sleep(monkeypatch):
    recorded: list[float] = []

    async def fake_sleep(duration: float) -> None:
        recorded.append(duration)

    monkeypatch.setattr("nova.llm.faker.asyncio.sleep", fake_sleep)
    provider = FakerLLMProvider(seed=1, reasoning_probability=1, stream_delay=0.0)

    _ = [
        event async for event in provider.chat_stream(
            [{"role": "user", "content": "Hello"}]
        )
    ]

    assert recorded == []
