"""Per-agent ownership of structured memory.

Verifies that ``agent``-scoped memory is private to the primary agent that
wrote it, that ``user``-scoped memory stays shared across agents, and that
sub-agents are never given the memory toolset.
"""

import pytest
import pytest_asyncio

from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.memory.agent_context import set_current_agent_key
from nova.memory.models import MemoryWriteRequest
from nova.memory.service import MemoryService


@pytest_asyncio.fixture
async def service():
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    yield MemoryService(data_source=database)
    await database.close()


@pytest.fixture(autouse=True)
def _reset_agent_context():
    set_current_agent_key(None)
    yield
    set_current_agent_key(None)


def _agent_request(key: str, content: str) -> MemoryWriteRequest:
    return MemoryWriteRequest(
        key=key,
        content=content,
        summary=content,
        scope="agent",
        memory_type="fact",
    )


@pytest.mark.asyncio
async def test_agent_memory_is_private_to_its_owner(service):
    set_current_agent_key("alice")
    await service.save(_agent_request("name", "You are Alice."))

    set_current_agent_key("bob")
    await service.save(_agent_request("name", "You are Bob."))

    bob_view = await service.list_memories(scope="agent")
    assert [record.content for record in bob_view] == ["You are Bob."]

    set_current_agent_key("alice")
    alice_view = await service.list_memories(scope="agent")
    assert [record.content for record in alice_view] == ["You are Alice."]


@pytest.mark.asyncio
async def test_same_key_under_agent_scope_does_not_collide(service):
    set_current_agent_key("alice")
    alice_record, alice_created = await service.save(_agent_request("name", "Alice"))

    set_current_agent_key("bob")
    bob_record, bob_created = await service.save(_agent_request("name", "Bob"))

    assert alice_created is True
    assert bob_created is True
    assert alice_record.id != bob_record.id


@pytest.mark.asyncio
async def test_user_memory_is_shared_across_agents(service):
    set_current_agent_key("alice")
    await service.save(
        MemoryWriteRequest(
            key="user_name",
            content="The user is Dana.",
            summary="user name",
            scope="user",
            memory_type="fact",
        )
    )

    set_current_agent_key("bob")
    bob_view = await service.list_memories(scope="user")
    assert [record.content for record in bob_view] == ["The user is Dana."]


@pytest.mark.asyncio
async def test_agent_view_includes_own_agent_and_global_user(service):
    set_current_agent_key("alice")
    await service.save(
        MemoryWriteRequest(
            key="user_name",
            content="The user is Dana.",
            summary="user name",
            scope="user",
            memory_type="fact",
        )
    )
    await service.save(_agent_request("name", "You are Alice."))

    set_current_agent_key("bob")
    await service.save(_agent_request("name", "You are Bob."))

    set_current_agent_key("alice")
    contents = {record.content for record in await service.list_memories(scope="all")}
    assert contents == {"The user is Dana.", "You are Alice."}


@pytest.mark.asyncio
async def test_agent_scope_without_active_agent_is_refused(service):
    set_current_agent_key(None)
    with pytest.raises(ValueError):
        await service.save(_agent_request("name", "orphaned"))


@pytest.mark.asyncio
async def test_delete_agent_memory_targets_only_owner(service):
    set_current_agent_key("alice")
    await service.save(_agent_request("name", "Alice"))
    set_current_agent_key("bob")
    await service.save(_agent_request("name", "Bob"))

    set_current_agent_key("alice")
    deleted = await service.delete(key="name", scope="agent")
    assert deleted == 1

    set_current_agent_key("bob")
    bob_view = await service.list_memories(scope="agent")
    assert [record.content for record in bob_view] == ["Bob"]


def test_sub_agent_does_not_register_memory_tools():
    from nova.agent.toolset import _MEMORY_TOOL_NAMES, ToolsetBuilder
    from nova.tools.registry import ToolRegistry

    class _StubSkillService:
        def list_skills(self):
            return []

    registry = ToolRegistry()
    builder = ToolsetBuilder(
        registry=registry,
        skill_service=_StubSkillService(),
        approval=None,
        is_sub_agent=True,
    )
    builder._register_builtin_tools()

    registered = set(registry.tools.keys())
    assert registered.isdisjoint(_MEMORY_TOOL_NAMES)
