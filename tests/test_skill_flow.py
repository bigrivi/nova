from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from nova import Agent, AgentConfig
from nova.agent.core import AgentEvent
from nova.db.database import Database, DatabaseConfig
from nova.llm.provider import Done, LLMProvider, TextDelta, ToolCall


def _write_skill(skills_dir: Path) -> None:
    skill_dir = skills_dir / "code-review"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: code-review\n"
        "description: Review code changes.\n"
        "allowed-tools: [read, grep]\n"
        "---\n\n"
        "# Code Review\n\n"
        "Focus on correctness first.\n",
        encoding="utf-8",
    )


class SkillFlowProvider(LLMProvider):
    def __init__(self) -> None:
        self._turn = 0

    async def chat(self, messages, model="gpt-4o", stream=False, tools=None, **kwargs):
        return Done(content="", tool_calls=[])

    async def chat_stream(self, messages, model="gpt-4o", tools=None, **kwargs):
        self._turn += 1
        if self._turn == 1:
            yield ToolCall(id="skill-1", name="list_skills", arguments="{}")
            yield Done(content="", tool_calls=[])
            return

        if self._turn == 2:
            tool_messages = [msg for msg in messages if getattr(msg, "role", "") == "tool"]
            assert tool_messages
            assert "Available skills" in tool_messages[-1].content
            assert "code-review" in tool_messages[-1].content
            yield ToolCall(
                id="skill-2",
                name="load_skill",
                arguments='{"skill_name":"code-review"}',
            )
            yield Done(content="", tool_calls=[])
            return

        tool_messages = [msg for msg in messages if getattr(msg, "role", "") == "tool"]
        assert tool_messages
        assert "Full SKILL.md:" in tool_messages[-1].content
        assert "# Code Review" in tool_messages[-1].content
        yield TextDelta(content="Skill loaded successfully.")
        yield Done(content="Skill loaded successfully.", tool_calls=[])

    async def count_tokens(self, text: str, model: str = None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


@pytest_asyncio.fixture
async def db():
    database = Database(DatabaseConfig(path=":memory:"))
    await database.connect()

    from nova.db import database as db_module

    old_db = db_module._db
    db_module._db = database
    yield database
    await database.close()
    db_module._db = old_db


@pytest.mark.asyncio
async def test_agent_skill_flow_uses_list_skills_then_load_skill(monkeypatch, tmp_path, db):
    home = tmp_path / "nova-home"
    monkeypatch.setenv("NOVA_HOME", str(home))
    _write_skill(home / "skills")

    agent = Agent(
        config=AgentConfig(model="test-model", max_iterations=4, show_context_stats=False),
        llm_provider=SkillFlowProvider(),
    )
    agent.register_all_tools()

    events = []
    async for event, data in agent.chat_stream("Use the available skill if helpful."):
        events.append((event, data))

    tool_calls = [data for event, data in events if event == AgentEvent.TOOL_CALL]
    done_payloads = [data for event, data in events if event == AgentEvent.DONE]

    assert [tool_call.name for tool_call in tool_calls] == ["list_skills", "load_skill"]
    assert done_payloads[-1]["reason"] == "completed"
    assert "Skill loaded successfully." in done_payloads[-1]["content"]
