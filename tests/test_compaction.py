"""
Compaction Module Tests using pytest
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from nova.agent.compaction import (
    estimate_tokens,
    snip_old_tool_results,
    find_split_point,
    should_compact,
    get_context_limit,
    _get_content,
    _get_role,
    _get_tool_calls,
    _get_tool_call_ids,
    _get_tool_call_id,
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
        # "Hello" = 5 chars, 5/4=1, 1*1.2=1
        assert tokens > 0  # 1 > 0

    def test_multiple_messages(self):
        messages = [
            MockMessage("1", "user", "Hello, how are you?"),  # 18 chars
            MockMessage("2", "assistant", "I'm doing well!"),  # 18 chars
            MockMessage("3", "user", "Can you help me?"),  # 17 chars
        ]
        tokens = estimate_tokens(messages)
        # total=53 chars, 53/4=13, 13*1.2=15.6->15
        assert tokens > 10  # Updated for new chars/4 * 1.2 formula

    def test_long_content(self):
        messages = [MockMessage("1", "user", "A" * 1000)]
        tokens = estimate_tokens(messages)
        # 1000 chars, 1000/4=250, 250*1.2=300
        assert tokens >= 300  # Updated: use >= instead of >


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
        result = snip_old_tool_results(messages, max_chars=2000, preserve_last_n_messages=2)
        
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
        result = snip_old_tool_results(messages, preserve_last_n_messages=2)
        
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
            turns_since_compact=0,
            last_compacted_at=None,
        )

    def test_compact_by_token_threshold(self):
        model_max_tokens = 10000
        threshold = int(model_max_tokens * 0.7)
        
        assert should_compact(
            message_count=10,
            token_count=threshold + 1000,
            turns_since_compact=5,
            last_compacted_at=None,
            model_max_tokens=model_max_tokens,
        )

    def test_no_compact_below_threshold(self):
        model_max_tokens = 10000
        threshold = int(model_max_tokens * 0.7)
        
        assert not should_compact(
            message_count=10,
            token_count=threshold - 1000,
            turns_since_compact=5,
            last_compacted_at=None,
            model_max_tokens=model_max_tokens,
        )

    def test_compact_by_message_count(self):
        assert should_compact(
            message_count=101,
            token_count=100,
            turns_since_compact=5,
            last_compacted_at=None,
        )

    def test_no_compact_at_100_messages(self):
        assert not should_compact(
            message_count=100,
            token_count=100,
            turns_since_compact=5,
            last_compacted_at=None,
        )

    def test_compact_by_turn_count(self):
        import time
        now = int(time.time() * 1000)
        
        assert should_compact(
            message_count=10,
            token_count=1000,
            turns_since_compact=25,
            last_compacted_at=now - 3600000,
            max_turns_between_compact=20,
        )

    def test_no_compact_few_turns(self):
        import time
        now = int(time.time() * 1000)
        
        assert not should_compact(
            message_count=10,
            token_count=1000,
            turns_since_compact=15,
            last_compacted_at=now - 3600000,
            max_turns_between_compact=20,
        )


class TestGetContextLimitWithMargin:
    def test_with_provider_joint_lookup(self):
        """Provider + model joint lookup returns correct limit."""
        from nova.llm.tokenizer import get_context_limit_with_margin
        
        mock_settings = MagicMock()
        mock_settings.providers = {
            "ollama": MagicMock(models={"gemma4:26b": {"limit": {"context": 32000}}}),
        }
        
        with patch("nova.settings.get_settings", return_value=mock_settings):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit_with_margin("gemma4:26b", "ollama")
            assert result == int(32000 / 1.2)

    def test_with_provider_context_window_fallback(self):
        """Falls back to context_window when limit.context missing."""
        from nova.llm.tokenizer import get_context_limit_with_margin
        
        mock_settings = MagicMock()
        mock_settings.providers = {
            "anthropic": MagicMock(models={"claude-3-sonnet": {"context_window": 200000}}),
        }
        
        with patch("nova.settings.get_settings", return_value=mock_settings):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit_with_margin("claude-3-sonnet", "anthropic")
            assert result == int(200000 / 1.2)

    def test_unknown_provider_hardcoded_fallback(self):
        """Falls back to hardcoded defaults for unknown provider."""
        from nova.llm.tokenizer import get_context_limit_with_margin
        
        mock_settings = MagicMock()
        mock_settings.providers = {}
        
        with patch("nova.settings.get_settings", return_value=mock_settings):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit_with_margin("gpt-4o", "unknown")
            assert result == 106666

    def test_get_context_limit_passes_provider(self):
        """get_context_limit passes provider to get_context_limit_with_margin."""
        mock_settings = MagicMock()
        mock_settings.providers = {
            "openai": MagicMock(models={"gpt-4o": {"limit": {"context": 200000}}}),
        }
        
        with patch("nova.settings.get_settings", return_value=mock_settings):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit("gpt-4o", "openai")
            assert result == int(200000 / 1.2)


class TestGetContextLimit:
    def test_gpt4o(self):
        # 128000 / 1.2 = 106666
        assert get_context_limit("gpt-4o", "openai") == 106666

    def test_gemma(self):
        # 32000 / 1.2 = 26666
        assert get_context_limit("gemma4:26b", "ollama") == 26666

    def test_unknown_model(self):
        # 128000 / 1.2 = 106666
        assert get_context_limit("unknown-model", "openai") == 106666


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

    def test_get_tool_call_ids_from_list(self):
        msg = MockMessage("1", "assistant", "", tool_calls=[{"id": "call_123"}, {"id": "call_456"}])
        ids = _get_tool_call_ids(msg)
        assert ids == ["call_123", "call_456"]

    def test_get_tool_call_ids_from_json_string(self):
        msg = MockMessage("1", "assistant", "", tool_calls='[{"id": "call_abc"}]')
        ids = _get_tool_call_ids(msg)
        assert ids == ["call_abc"]

    def test_get_tool_call_ids_empty(self):
        msg = MockMessage("1", "user", "hello")
        assert _get_tool_call_ids(msg) == []

    def test_get_tool_call_id_from_object(self):
        msg = MockMessage("2", "tool", "result")
        msg.tool_call_id = "call_xyz"
        assert _get_tool_call_id(msg) == "call_xyz"

    def test_get_tool_call_id_from_dict(self):
        msg = {"role": "tool", "tool_call_id": "call_xyz"}
        assert _get_tool_call_id(msg) == "call_xyz"

    def test_get_tool_call_id_empty(self):
        msg = MockMessage("2", "tool", "result")
        assert _get_tool_call_id(msg) == ""


@pytest.mark.asyncio
async def test_compact_orphaned_tool_response_is_also_compacted():
    """When split separates tool_call assistant from its response, the orphaned
    tool response is also compacted to avoid tool message without preceding tool_calls."""
    from nova.agent.compaction import compact
    from nova.db.sqlite_repository import SqliteRepository
    from nova.db.config import DatabaseConfig
    from nova.session.models import MessageFilter
    from nova.session.manager import SessionContext

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()

    try:
        session_id = "test-orphan-session"
        session = SessionContext.create()
        session.id = session_id
        await db.save_session(session)

        # 4 messages: [0] user, [1] assistant with tool_calls, [2] tool response, [3] user
        await db.add_message(session_id, "user", "search for something")
        await db.add_message(
            session_id, "assistant", "",
            tool_calls=[{"id": "call_orphan", "type": "function",
                         "function": {"name": "web_search", "arguments": '{"q":"test"}'}}],
        )
        await db.add_message(
            session_id, "tool", "search results here",
            tool_call_id="call_orphan",
        )
        await db.add_message(session_id, "user", "tell me more")

        # Force split at 2: compact [0,1], keep [2,3]
        # [1] = assistant with call_orphan is compacted → [2] should also be compacted
        with patch("nova.agent.compaction.find_split_point", return_value=2):
            mock_llm = AsyncMock()
            mock_llm.chat.return_value = MagicMock(content="Summary of conversation")

            await compact(session_id, db, mock_llm, "gpt-4o")

        # Active messages should NOT include the orphaned tool response
        active = await db.get_messages(session_id)
        for msg in active:
            assert msg.tool_call_id != "call_orphan", \
                f"orphaned tool response {msg.id} should be compacted"

        # The last user message should still be active
        assert any(m.content == "tell me more" for m in active)

        # Summary was inserted
        assert any(m.summary == 1 for m in active)

        # All messages (including compacted) — verify tool response IS compacted
        all_msgs = await db.get_messages(session_id, MessageFilter(include_compacted=True))
        orphan = [m for m in all_msgs if m.tool_call_id == "call_orphan"]
        assert len(orphan) == 1
        assert orphan[0].compacted == 1, \
            f"orphaned tool response should have compacted=1, got {orphan[0].compacted}"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_compact_with_real_llm():
    """Test compaction with real LLM (requires Ollama running)"""
    from nova.db.sqlite_repository import SqliteRepository
    from nova.db.config import DatabaseConfig
    from nova.session.manager import SessionContext
    from nova.agent.compaction import compact
    from nova.llm import OllamaProvider
    
    db = SqliteRepository(DatabaseConfig(path=":memory:"))
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
async def test_prepare_and_run_compaction_with_real_llm():
    from nova.db.sqlite_repository import SqliteRepository
    from nova.db.config import DatabaseConfig
    from nova.session.manager import SessionContext
    from nova.agent.compaction import prepare_compaction, run_compaction_plan
    from nova.llm import OllamaProvider

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
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
        messages = await db.get_messages(session_id)
        plan = await prepare_compaction(
            session_id=session_id,
            messages=messages,
            last_compacted_at=None,
            db=db,
            model="gemma4:26b",
        )

        assert isinstance(plan.needs_compaction, bool)
        assert plan.message_count == len(messages)
        await run_compaction_plan(plan, db, llm, "gemma4:26b", messages=messages)
    finally:
        await db.close()


class MockTimedMessage(MockMessage):
    def __init__(self, id, role, content, tool_calls=None, tool_call_id=None, time_created=0):
        super().__init__(id, role, content, tool_calls)
        self.tool_call_id = tool_call_id
        self.time_created = time_created


class TestCountTurnsSinceCompact:
    def test_zero_without_last_compacted_at(self):
        from nova.agent.compaction import count_turns_since_compact

        messages = [MockTimedMessage(str(i), "user", "hi", time_created=i)
                    for i in range(30)]
        assert count_turns_since_compact(messages, None) == 0

    def test_counts_only_user_messages_after_compaction(self):
        from nova.agent.compaction import count_turns_since_compact

        messages = [
            MockTimedMessage("1", "user", "before", time_created=100),
            MockTimedMessage("2", "assistant", "before", time_created=110),
            MockTimedMessage("3", "user", "after", time_created=300),
            MockTimedMessage("4", "assistant", "after", time_created=310),
            MockTimedMessage("5", "tool", "after", time_created=320),
            MockTimedMessage("6", "user", "after", time_created=330),
        ]
        assert count_turns_since_compact(messages, 200) == 2

    def test_cumulative_history_does_not_trigger_perpetual_compaction(self):
        from nova.agent.compaction import count_turns_since_compact

        messages = [MockTimedMessage(str(i), "user", "old", time_created=i)
                    for i in range(1, 200)]
        messages.append(MockTimedMessage("new", "user", "new", time_created=9999))
        turns = count_turns_since_compact(messages, 5000)
        assert turns == 1
        assert not should_compact(
            message_count=len(messages),
            token_count=10,
            turns_since_compact=turns,
            last_compacted_at=5000,
            model_max_tokens=1000000,
            max_messages=100000,
            max_turns_between_compact=20,
        )


class TestCjkTokenEstimation:
    def test_cjk_is_not_underestimated_like_latin(self):
        from nova.llm.tokenizer import estimate_tokens_by_type

        chinese = "重构上下文压缩机制并修复配对问题" * 10
        latin = "refactor the context compaction mechanism now" * 10
        cjk_tokens = estimate_tokens_by_type(chinese)
        assert cjk_tokens >= len(chinese) * 0.9
        assert estimate_tokens_by_type(latin) <= len(latin) // 3

    def test_mixed_script_counted_per_script(self):
        from nova.llm.tokenizer import estimate_tokens_by_type

        mixed = "读取文件 read the file"
        cjk_count = 4
        expected = cjk_count + (len(mixed) - cjk_count) // 4
        assert estimate_tokens_by_type(mixed) == expected


class TestSplitPointPairing:
    def test_split_never_starts_with_tool_message(self):
        from nova.agent.compaction import _advance_to_safe_split

        messages = [
            MockTimedMessage("1", "user", "q"),
            MockTimedMessage("2", "assistant", "", tool_calls=[{"id": "a"}]),
            MockTimedMessage("3", "tool", "r1", tool_call_id="a"),
            MockTimedMessage("4", "tool", "r2", tool_call_id="a"),
            MockTimedMessage("5", "assistant", "done"),
        ]
        assert _advance_to_safe_split(messages, 2) == 4
        assert _advance_to_safe_split(messages, 3) == 4
        assert _advance_to_safe_split(messages, 4) == 4

    def test_zero_split_is_untouched(self):
        from nova.agent.compaction import _advance_to_safe_split

        messages = [MockTimedMessage("1", "tool", "r", tool_call_id="a")]
        assert _advance_to_safe_split(messages, 0) == 0

    def test_find_split_point_returns_safe_boundary(self):
        messages = [
            MockTimedMessage("1", "user", "x" * 4000),
            MockTimedMessage("2", "assistant", "", tool_calls=[{"id": "a"}]),
            MockTimedMessage("3", "tool", "y" * 4000, tool_call_id="a"),
            MockTimedMessage("4", "assistant", "z" * 40),
        ]
        split = find_split_point(messages, keep_ratio=0.3)
        assert split == 0 or _get_role(messages[split]) != "tool"


@pytest.mark.asyncio
async def test_chat_stream_loads_messages_once_per_request():
    """chat_stream owns the single message load; turn 1 reuses it, later turns reload."""
    from nova import Agent, AgentConfig
    from nova.agent.core import AgentEvent
    from nova.db.sqlite_repository import SqliteRepository
    from nova.db.config import DatabaseConfig
    from nova.db import database as db_module
    from nova.llm import ToolResult
    from nova.llm.provider import Done, LLMProvider, TextDelta, ToolCall

    class ScriptedProvider(LLMProvider):
        def __init__(self, scripts):
            self._scripts = scripts
            self._index = 0

        async def chat(self, messages, model="m", stream=False, tools=None, **kw):
            return Done(content="summary")

        async def chat_stream(self, messages, model="m", tools=None, **kw):
            script = self._scripts[min(self._index, len(self._scripts) - 1)]
            self._index += 1
            for item in script:
                await asyncio.sleep(0)
                yield item

        async def count_tokens(self, text, model=None):
            return len(text)

        def get_max_tokens(self, model):
            return 128000

    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    old_db = db_module._db
    db_module._db = database
    try:
        calls = {"n": 0}
        original_get_messages = database.get_messages

        async def counted(*args, **kwargs):
            calls["n"] += 1
            return await original_get_messages(*args, **kwargs)

        database.get_messages = counted

        agent = Agent(
            config=AgentConfig(model="test-model", max_iterations=1),
            llm_provider=ScriptedProvider([[TextDelta(content="hello")]]),
        )
        session_id = None
        async for event, data in agent.chat_stream("first"):
            if event == AgentEvent.SESSION:
                session_id = data
        assert calls["n"] == 1

        calls["n"] = 0
        agent2 = Agent(
            config=AgentConfig(model="test-model", max_iterations=3),
            llm_provider=ScriptedProvider([
                [ToolCall(id="t1", name="ok_tool", arguments="{}")],
                [TextDelta(content="done")],
            ]),
        )

        async def ok_tool() -> ToolResult:
            return ToolResult(success=True, content="ok")

        agent2.register_tool(ok_tool, name="ok_tool")
        async for _event, _data in agent2.chat_stream("second", session_id=session_id):
            pass
        assert calls["n"] == 2
    finally:
        await database.close()
        db_module._db = old_db
