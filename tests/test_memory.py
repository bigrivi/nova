import pytest
import pytest_asyncio

from nova import Agent, AgentConfig
from nova.agent.core import AgentEvent
from nova.memory.models import MemoryRecord, MemoryWriteRequest
from nova.memory.service import MemoryService
from nova.memory.tools import delete_memory, list_memories, save_memory, search_memory
from nova.db.database import Database, DatabaseConfig
from nova.llm import ToolResult
from nova.llm.provider import Done, LLMProvider, TextDelta, ToolCall


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
async def test_save_and_search_memory(db):
    result = await save_memory(
        key="answer_style",
        content="Respond with the conclusion first and keep it concise.",
        summary="User prefers concise answers.",
        scope="user",
        memory_type="preference",
        tags=["style", "user"],
    )

    assert result.success is True
    assert "Memory created." in result.content

    search_result = await search_memory(query="concise", scope="user")

    assert search_result.success is True
    assert "answer_style" in search_result.content
    assert "User prefers concise answers." in search_result.content


@pytest.mark.asyncio
async def test_save_memory_updates_existing_record(db):
    service = MemoryService()
    first, created = await service.save(
        request=MemoryWriteRequest(
            key="project_rule",
            content="Use the existing endpoint.",
            summary="Keep the current endpoint.",
            scope="project",
            memory_type="decision",
            tags=["api"],
        )
    )
    second, created_again = await service.save(
        request=MemoryWriteRequest(
            key="project_rule",
            content="Reuse the current endpoint instead of adding a new one.",
            summary="Reuse existing endpoint.",
            scope="project",
            memory_type="decision",
            tags=["api", "routing"],
        )
    )

    listed = await service.list_memories(scope="project")

    assert created is True
    assert created_again is False
    assert first.id == second.id
    assert len(listed) == 1
    assert listed[0].summary == "Reuse existing endpoint."


@pytest.mark.asyncio
async def test_session_memory_requires_session_id(db):
    result = await save_memory(
        key="active_task",
        content="Working on memory implementation.",
        summary="Current work item.",
        scope="session",
        memory_type="context",
    )

    assert result.success is False
    assert "session_id is required" in result.content


@pytest.mark.asyncio
async def test_list_and_delete_memory(db):
    create_result = await save_memory(
        key="repo_fact",
        content="Nova uses sqlite for session persistence.",
        summary="Session persistence uses sqlite.",
        scope="project",
        memory_type="fact",
    )
    assert create_result.success is True

    listed = await list_memories(scope="project")
    assert listed.success is True
    assert "repo_fact" in listed.content

    delete_result = await delete_memory(key="repo_fact", scope="project")
    assert delete_result.success is True
    assert "Deleted 1 memory record" in delete_result.content

    listed_after_delete = await list_memories(scope="project")
    assert listed_after_delete.success is True
    assert listed_after_delete.content == "No memories stored."


@pytest.mark.asyncio
async def test_search_memory_filters_by_session(db):
    await save_memory(
        key="session_note",
        content="This belongs to session one.",
        summary="Session one note.",
        scope="session",
        memory_type="context",
        session_id="session-1",
    )
    await save_memory(
        key="session_note",
        content="This belongs to session two.",
        summary="Session two note.",
        scope="session",
        memory_type="context",
        session_id="session-2",
    )

    result = await search_memory(
        query="session",
        scope="session",
        session_id="session-2",
    )

    assert result.success is True
    assert "session-2" in result.content
    assert "session-1" not in result.content


@pytest.mark.asyncio
async def test_search_memory_use_ai_can_select_non_top_keyword_candidate(db):
    service = MemoryService()
    await service.save(
        MemoryWriteRequest(
            key="response_style",
            content="Answer with the conclusion first and keep it concise.",
            summary="User prefers concise answers.",
            scope="user",
            memory_type="preference",
            tags=["style"],
        )
    )
    await service.save(
        MemoryWriteRequest(
            key="review_priority",
            content="Focus on bugs and regressions in code review.",
            summary="Review should focus on bugs first.",
            scope="user",
            memory_type="preference",
            tags=["review"],
        )
    )

    async def fake_ai_selector(query, candidates, limit):
        assert query == "how should I do code review"
        return [candidate for candidate in candidates if candidate.key == "review_priority"][:limit]

    results = await service.search(
        query="how should I do code review",
        scope="user",
        limit=1,
        use_ai=True,
        ai_selector=fake_ai_selector,
    )

    assert len(results) == 1
    assert results[0].key == "review_priority"


@pytest.mark.asyncio
async def test_search_memory_use_ai_falls_back_to_keyword_ranking_on_selector_error(db):
    service = MemoryService()
    await service.save(
        MemoryWriteRequest(
            key="response_style",
            content="Answer with the conclusion first and keep it concise.",
            summary="User prefers concise answers.",
            scope="user",
            memory_type="preference",
            tags=["style", "concise"],
        )
    )

    async def failing_selector(query, candidates, limit):
        raise RuntimeError("selector failed")

    results = await service.search(
        query="concise answer style",
        scope="user",
        limit=1,
        use_ai=True,
        ai_selector=failing_selector,
    )

    assert len(results) == 1
    assert results[0].key == "response_style"


def test_memory_ai_selection_messages_prefer_direct_match_rules():
    service = MemoryService()
    records = [
        MemoryRecord(
            id="id-1",
            key="response_style",
            content="Answer with the conclusion first and keep it concise.",
            summary="User prefers concise answers.",
            scope="user",
            memory_type="preference",
            tags=["style"],
        ),
        MemoryRecord(
            id="id-2",
            key="review_priority",
            content="Focus on bugs and regressions in code review.",
            summary="Review should focus on bugs first.",
            scope="user",
            memory_type="preference",
            tags=["review"],
        ),
    ]

    messages = service._build_ai_selection_messages(  # type: ignore[attr-defined]
        "how should I do code review",
        records,
        limit=1,
    )

    assert len(messages) == 2
    assert "Prefer memories whose summary or key directly matches" in messages[0].content
    assert "Use content only as supporting evidence or a tie-breaker" in messages[0].content
    assert "Prefer specific topical memories over generic writing-style" in messages[0].content
    assert "key=review_priority" in messages[1].content
    assert "summary: Review should focus on bugs first." in messages[1].content


def test_parse_ai_indices_accepts_wrapped_json_object():
    service = MemoryService()

    indices = service._parse_ai_indices(  # type: ignore[attr-defined]
        'I found the best matches.\n```json\n{"indices":[1,0,1]}\n```\nUse them.'
    )

    assert indices == [1, 0]


class MemoryToolFlowProvider(LLMProvider):
    def __init__(self):
        self._turn = 0

    async def chat(self, messages, model="gpt-4o", stream=False, tools=None, **kwargs):
        return Done(content="", tool_calls=[])

    async def chat_stream(self, messages, model="gpt-4o", tools=None, **kwargs):
        self._turn += 1
        if self._turn == 1:
            yield ToolCall(
                id="memory-1",
                name="search_memory",
                arguments='{"query":"preferred response style","scope":"user","limit":1}',
            )
            yield Done(content="", tool_calls=[])
            return

        tool_messages = [msg for msg in messages if getattr(msg, "role", "") == "tool"]
        assert tool_messages, "second model turn should receive tool output"
        assert "User prefers concise answers." in tool_messages[-1].content
        yield TextDelta(content="You prefer concise answers.")
        yield Done(content="You prefer concise answers.", tool_calls=[])

    async def count_tokens(self, text: str, model: str = None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


@pytest.mark.asyncio
async def test_agent_can_complete_memory_tool_flow(db):
    await save_memory(
        key="response_style",
        content="Answer with the conclusion first and keep it concise.",
        summary="User prefers concise answers.",
        scope="user",
        memory_type="preference",
    )

    agent = Agent(
        config=AgentConfig(model="test-model", max_iterations=3, show_context_stats=False),
        llm_provider=MemoryToolFlowProvider(),
    )
    agent.register_all_tools()

    events = []
    async for event, data in agent.chat_stream("What response style do I prefer?"):
        events.append((event, data))

    tool_calls = [data for event, data in events if event == AgentEvent.TOOL_CALL]
    tool_results = [data for event, data in events if event == AgentEvent.TOOL_RESULT]
    done_payloads = [data for event, data in events if event == AgentEvent.DONE]

    assert tool_calls
    assert tool_calls[0].name == "search_memory"
    assert tool_results
    assert tool_results[0]["tool"] == "search_memory"
    assert "User prefers concise answers." in tool_results[0]["result"].content
    assert done_payloads[-1]["reason"] == "completed"
    assert "concise answers" in done_payloads[-1]["content"]
