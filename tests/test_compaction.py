"""
Compaction Module Tests using pytest
"""

import pytest
import asyncio

from nova.agent.compaction import (
    estimate_tokens,
    snip_old_tool_results,
    find_split_point,
    should_compact,
    get_context_limit,
    _get_content,
    _get_role,
    _get_tool_calls,
    _get_msg_id,
)


class MockMessage:
    def __init__(self, id: str, role: str, content: str, tool_calls=None):
        self.id = id
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []


class TestEstimateTokens:
    def test_empty_messages(self):
        assert estimate_tokens([]) == 0

    def test_single_message(self):
        messages = [MockMessage("1", "user", "Hello")]
        tokens = estimate_tokens(messages)
        assert tokens > 0

    def test_multiple_messages(self):
        messages = [
            MockMessage("1", "user", "Hello, how are you?"),
            MockMessage("2", "assistant", "I'm doing well!"),
            MockMessage("3", "user", "Can you help me?"),
        ]
        tokens = estimate_tokens(messages)
        assert tokens > 30

    def test_long_content(self):
        messages = [MockMessage("1", "user", "A" * 1000)]
        tokens = estimate_tokens(messages)
        assert tokens > 300


class TestSnipOldToolResults:
    def test_snip_long_tool_message(self):
        messages = [
            MockMessage("1", "tool", "A" * 3000),
            MockMessage("2", "tool", "B" * 100),
            MockMessage("3", "user", "Hello"),
            MockMessage("4", "assistant", "Hi!"),
            MockMessage("5", "tool", "C" * 500),
            MockMessage("6", "tool", "D" * 100),
        ]
        result = snip_old_tool_results(messages, max_chars=2000, preserve_last_n_turns=2)
        
        assert "[... " in result[0].content
        assert " chars snipped " in result[0].content
        assert result[1].content == "B" * 100
        assert result[2].content == "Hello"

    def test_preserves_recent_turns(self):
        messages = [
            MockMessage("1", "tool", "A" * 5000),
            MockMessage("2", "tool", "B" * 5000),
            MockMessage("3", "tool", "C" * 100),
            MockMessage("4", "tool", "D" * 100),
        ]
        result = snip_old_tool_results(messages, preserve_last_n_turns=2)
        
        assert "[... " in result[0].content
        assert "[... " in result[1].content
        assert result[2].content == "C" * 100
        assert result[3].content == "D" * 100

    def test_short_tool_message_unchanged(self):
        messages = [
            MockMessage("1", "tool", "A" * 100),
            MockMessage("2", "user", "Hello"),
        ]
        result = snip_old_tool_results(messages)
        
        assert result[0].content == "A" * 100

    def test_non_tool_message_unchanged(self):
        messages = [
            MockMessage("1", "user", "Hello"),
            MockMessage("2", "assistant", "Hi!"),
        ]
        result = snip_old_tool_results(messages)
        
        assert result[0].content == "Hello"
        assert result[1].content == "Hi!"


class TestFindSplitPoint:
    def test_single_message(self):
        messages = [MockMessage("1", "user", "Hello")]
        split = find_split_point(messages)
        assert split == 0

    def test_ten_messages(self):
        messages = []
        for i in range(10):
            content = f"Message {i}: " + "x" * 100
            messages.append(MockMessage(str(i), "user", content))
        
        split = find_split_point(messages, keep_ratio=0.3)
        
        assert 0 <= split < 10

    def test_returns_index_not_count(self):
        messages = [
            MockMessage(str(i), "user", "x" * 100) for i in range(5)
        ]
        split = find_split_point(messages)
        
        assert isinstance(split, int)
        assert 0 <= split <= 4


class TestShouldCompact:
    def test_no_compact_when_empty(self):
        assert not should_compact(
            message_count=0,
            token_count=0,
            turn_count=0,
            last_compacted_at=None,
        )

    def test_compact_by_token_threshold(self):
        model_max_tokens = 10000
        threshold = int(model_max_tokens * 0.7)
        
        assert should_compact(
            message_count=10,
            token_count=threshold + 1000,
            turn_count=5,
            last_compacted_at=None,
            model_max_tokens=model_max_tokens,
        )

    def test_no_compact_below_threshold(self):
        model_max_tokens = 10000
        threshold = int(model_max_tokens * 0.7)
        
        assert not should_compact(
            message_count=10,
            token_count=threshold - 1000,
            turn_count=5,
            last_compacted_at=None,
            model_max_tokens=model_max_tokens,
        )

    def test_compact_by_message_count(self):
        assert should_compact(
            message_count=101,
            token_count=100,
            turn_count=5,
            last_compacted_at=None,
        )

    def test_no_compact_at_100_messages(self):
        assert not should_compact(
            message_count=100,
            token_count=100,
            turn_count=5,
            last_compacted_at=None,
        )

    def test_compact_by_turn_count(self):
        import time
        now = int(time.time() * 1000)
        
        assert should_compact(
            message_count=10,
            token_count=1000,
            turn_count=25,
            last_compacted_at=now - 3600000,
            max_turns_between_compact=20,
        )

    def test_no_compact_few_turns(self):
        import time
        now = int(time.time() * 1000)
        
        assert not should_compact(
            message_count=10,
            token_count=1000,
            turn_count=15,
            last_compacted_at=now - 3600000,
            max_turns_between_compact=20,
        )


class TestGetContextLimit:
    def test_gpt4o(self):
        assert get_context_limit("gpt-4o") == 128000

    def test_gemma(self):
        assert get_context_limit("gemma4:26b") == 32000

    def test_unknown_model(self):
        assert get_context_limit("unknown-model") == 128000


class TestHelperFunctions:
    def test_get_content_with_object(self):
        msg = MockMessage("1", "user", "Hello")
        assert _get_content(msg) == "Hello"

    def test_get_content_with_dict(self):
        msg = {"content": "Hello"}
        assert _get_content(msg) == "Hello"

    def test_get_content_empty(self):
        msg = MockMessage("1", "user", "")
        assert _get_content(msg) == ""

    def test_get_role_with_object(self):
        msg = MockMessage("1", "user", "Hello")
        assert _get_role(msg) == "user"

    def test_get_role_with_dict(self):
        msg = {"role": "assistant"}
        assert _get_role(msg) == "assistant"

    def test_get_msg_id_with_object(self):
        msg = MockMessage("123", "user", "Hello")
        assert _get_msg_id(msg) == "123"

    def test_get_msg_id_with_dict(self):
        msg = {"id": "456"}
        assert _get_msg_id(msg) == "456"

    def test_get_tool_calls(self):
        msg = MockMessage("1", "assistant", "Hi", tool_calls=[{"name": "read"}])
        assert len(_get_tool_calls(msg)) == 1


@pytest.mark.asyncio
async def test_compact_with_real_llm():
    """Test compaction with real LLM (requires Ollama running)"""
    from nova.db.database import Database, DatabaseConfig
    from nova.session.manager import SessionContext
    from nova.agent.compaction import compact
    from nova.llm import OllamaProvider
    
    db = Database(DatabaseConfig(path=":memory:"))
    await db.connect()
    
    try:
        session_id = "test-session-123"
        session = SessionContext.create()
        session.id = session_id
        await db.save_session(session)
        
        messages_data = [
            (session_id, "user", "Hello, how are you?"),
            (session_id, "assistant", "I'm doing well, thanks for asking!"),
            (session_id, "tool", "Command output: file1.txt\nfile2.txt\nfile3.txt"),
            (session_id, "assistant", "I can see the files in the directory."),
        ]
        
        for sid, role, content in messages_data:
            await db.add_message(sid, role, content)
        
        llm = OllamaProvider()
        
        await compact(session_id, db, llm, "gemma4:26b")
        
        result_messages = await db.get_messages(session_id)
        summary_messages = [m for m in result_messages if m.summary == 1]
        
        assert len(summary_messages) >= 1
        assert "Previous conversation summary" in summary_messages[0].content
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_maybe_compact_with_real_llm():
    """Test maybe_compact with real LLM"""
    from nova.db.database import Database, DatabaseConfig
    from nova.session.manager import SessionContext
    from nova.agent.compaction import maybe_compact
    from nova.llm import OllamaProvider
    
    db = Database(DatabaseConfig(path=":memory:"))
    await db.connect()
    
    try:
        session_id = "test-session-456"
        session = SessionContext.create()
        session.id = session_id
        await db.save_session(session)
        
        for i in range(5):
            role = "user" if i % 2 == 0 else "assistant"
            content = f"Message {i} with some content"
            await db.add_message(session_id, role, content)
        
        llm = OllamaProvider()
        
        did_compact = await maybe_compact(
            session_id=session_id,
            message_count=5,
            turn_count=5,
            last_compacted_at=None,
            db=db,
            llm=llm,
            model="gemma4:26b",
        )
        
        assert isinstance(did_compact, bool)
    finally:
        await db.close()
