import pytest
import pytest_asyncio

from nova import Agent, AgentConfig
from nova.agent.core import AgentEvent
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.llm.provider import Done, LLMProvider, TextDelta, ToolCall
from nova.memory.models import MemoryRecord, MemoryWriteRequest
from nova.memory.service import MemoryService
from nova.memory.tools import MemoryTools

_memory_tools = MemoryTools(agent_key=None)
save_memory = _memory_tools.save_memory
search_memory = _memory_tools.search_memory
delete_memory = _memory_tools.delete_memory
list_memories = _memory_tools.list_memories


@pytest_asyncio.fixture
async def db():
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
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
        key="answer_style",  # stored as "answer-style": see the canonical-key rule
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
    assert "answer-style" in search_result.content
    assert "User prefers concise answers." in search_result.content


@pytest.mark.asyncio
async def test_search_rejects_content_only_single_term_match(db):
    await save_memory(
        key="animal_fact",
        content="A zebra crossed the road yesterday.",
        summary="Some general note.",
        scope="user",
        memory_type="fact",
        tags=[],
    )

    result = await search_memory(query="zebra", scope="user")

    assert result.success is True
    assert "No relevant memories" in result.content


@pytest.mark.asyncio
async def test_search_accepts_summary_or_key_match(db):
    await save_memory(
        key="python_notes",  # stored as "notes-python"
        content="Use ruff for linting.",
        summary="Python development notes.",
        scope="user",
        memory_type="fact",
        tags=["python"],
    )

    result = await search_memory(query="python", scope="user")

    assert result.success is True
    assert "notes-python" in result.content


@pytest.mark.asyncio
async def test_search_results_warn_about_relevance(db):
    await save_memory(
        key="answer_style",
        content="Respond with the conclusion first and keep it concise.",
        summary="User prefers concise answers.",
        scope="user",
        memory_type="preference",
        tags=["style"],
    )

    result = await search_memory(query="concise", scope="user")

    assert result.success is True
    assert "Only use those directly relevant" in result.content


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
        key="repo_fact",  # stored as "fact-repo"
        content="Nova uses sqlite for session persistence.",
        summary="Session persistence uses sqlite.",
        scope="project",
        memory_type="fact",
    )
    assert create_result.success is True

    listed = await list_memories(scope="project")
    assert listed.success is True
    assert "fact-repo" in listed.content

    # Deleting by the spelling it was saved under, which canonicalises on the way
    # in: identity is the set of words, not the punctuation.
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
        return [
            candidate for candidate in candidates if candidate.key == "review_priority"
        ][:limit]

    results = await service.search(
        query="how should I do code review",
        scope="user",
        limit=1,
        use_ai=True,
        ai_selector=fake_ai_selector,
    )

    assert len(results) == 1
    assert results[0].key == "priority-review"


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
    assert results[0].key == "response-style"


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
    assert (
        "Prefer memories whose summary or key directly matches" in messages[0].content
    )
    assert (
        "Use content only as supporting evidence or a tie-breaker"
        in messages[0].content
    )
    assert (
        "Prefer specific topical memories over generic writing-style"
        in messages[0].content
    )
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

    async def count_tokens(self, text: str, model: str | None = None) -> int:
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
        config=AgentConfig(model="test-model", max_iterations=3),
        llm_provider=MemoryToolFlowProvider(),
    )
    await agent.register_all_tools()

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


class SaveSessionMemoryProvider(LLMProvider):
    """First turn requests save_memory with scope=session and no session_id."""

    def __init__(self):
        self._turn = 0

    async def chat(self, messages, model="gpt-4o", stream=False, tools=None, **kwargs):
        return Done(content="", tool_calls=[])

    async def chat_stream(self, messages, model="gpt-4o", tools=None, **kwargs):
        self._turn += 1
        if self._turn == 1:
            yield ToolCall(
                id="save-session-1",
                name="save_memory",
                arguments=(
                    '{"key":"active_task","content":"Working on the Nova memory system.",'
                    '"summary":"Current work item.","scope":"session","memory_type":"context"}'
                ),
            )
            yield Done(content="", tool_calls=[])
            return
        yield TextDelta(content="Done.")
        yield Done(content="Done.", tool_calls=[])

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


@pytest.mark.asyncio
async def test_agent_injects_current_session_id_into_save_memory(db):
    agent = Agent(
        config=AgentConfig(model="test-model", max_iterations=3),
        llm_provider=SaveSessionMemoryProvider(),
    )
    await agent.register_all_tools()

    session_id = None
    async for event, data in agent.chat_stream("Save my current task."):
        if event == AgentEvent.SESSION:
            session_id = data

    assert session_id
    saved = await MemoryService().list_memories(scope="session", session_id=session_id)
    assert len(saved) == 1
    assert saved[0].key == "active-task"
    assert saved[0].scope == "session"
    assert saved[0].session_id == session_id


# ── a key is the set of its words, not the spelling the model typed ──────


@pytest.mark.asyncio
async def test_two_spellings_of_one_fact_are_one_memory(db):
    """The failure this came from: four rows, three values, one question.

    An agent asked to recall a codename searched memory and got four records
    back -- ``rollback-codename``, ``codename-rollback``, ``rollback_codename``
    and ``ops-rollback-codename`` -- written across four sessions, with three
    different values in them. Nothing marked one as current, so it picked the
    stale one and said so.

    ``upsert`` already overwrites on an exact key match; what was missing was
    an identity for "same fact, other words". Punctuation and word order are
    not evidence of a different fact.
    """
    from nova.memory.service import MemoryService

    service = MemoryService()

    for spelling in ("rollback-codename", "Rollback Codename", "rollback_codename"):
        await service.save(
            MemoryWriteRequest(
                key=spelling,
                content="The rollback codename is HARBOUR-DCB79B.",
                summary="Rollback codename",
                scope="user",
                memory_type="fact",
            )
        )

    records = await service.list_memories(scope="user")
    assert len(records) == 1, f"the same fact was stored {len(records)} times"
    assert records[0].content.endswith("HARBOUR-DCB79B.")

    # A correction replaces it rather than sitting beside it.
    await service.save(
        MemoryWriteRequest(
            key="codename rollback",
            content="The rollback codename is HARBOUR-QQ4481.",
            summary="Rollback codename",
            scope="user",
            memory_type="fact",
        )
    )
    again = await service.list_memories(scope="user")
    assert len(again) == 1, "the correction added a row instead of updating one"
    found = await service.search(query="rollback codename", scope="user")
    assert found and "QQ4481" in found[0].content, (
        "search still returns the superseded value"
    )


@pytest.mark.asyncio
async def test_a_key_with_an_extra_word_stays_its_own_memory(db):
    """The conservative half: merging must not invent facts.

    Normalising harder -- stemming, stop-words, prefix matching -- would fold
    ``ops-rollback-codename`` into ``rollback-codename``, and a rule that merges
    two different facts is worse than one that leaves four spellings of one.
    """
    from nova.memory.service import MemoryService

    service = MemoryService()
    for key in ("rollback-codename", "ops-rollback-codename"):
        await service.save(
            MemoryWriteRequest(
                key=key,
                content=f"stored under {key}",
                summary=key,
                scope="user",
                memory_type="fact",
            )
        )

    assert len(await service.list_memories(scope="user")) == 2


def test_currency_is_reported_in_a_form_a_reader_can_rank():
    """``1791676861851`` is not a currency signal.

    Choosing between memories meant comparing epoch integers by eye. The same
    information as a date and an age ranks itself.
    """
    import time

    from nova.memory.models import MemoryRecord
    from nova.memory.tools import _format_memory, _when

    stale = MemoryRecord(
        id="a",
        key="k",
        scope="user",
        memory_type="fact",
        content="c",
        summary="s",
        updated_at=int((time.time() - 86400 * 3) * 1000),
    )
    fresh = MemoryRecord(
        id="b",
        key="k",
        scope="user",
        memory_type="fact",
        content="c",
        summary="s",
        updated_at=int(time.time() * 1000),
    )

    assert "3 days ago" in _format_memory(stale)
    assert "just now" in _format_memory(fresh)
    # Epoch zero is 1970, which is the age it says rather than a special case:
    # an ancient memory reads as ancient instead of crashing the caller.
    assert "1970" in _when(0) and "ago" in _when(0)


def test_search_tells_the_agent_that_the_user_outranks_memory():
    """The rule the failing agent needed, where it would have read it.

    It found a stale memory, asked the user which codename was right, got no
    answer, and answered from the memory anyway -- while admitting the value it
    had just been told was never stored. The rule belongs in the tool it called
    to get there.
    """
    import nova.memory.tools  # noqa: F401 -- registers the schemas
    import nova.tools.registry as registry

    description = registry._tool_metadata["search_memory"].get("description", "")
    assert "stale" in description and "the user is right" in description, (
        "search_memory does not say that a current statement outranks a memory"
    )
