"""
Compaction Module Tests using pytest
"""

import pytest
import asyncio
import contextlib
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
    def test_snips_output_beyond_the_token_budget(self):
        messages = [
            MockMessage("1", "tool", "A" * 30000),
            MockMessage("2", "tool", "B" * 100),
            MockMessage("3", "user", "Hello"),
            MockMessage("4", "assistant", "Hi!"),
            MockMessage("5", "tool", "C" * 500),
        ]
        result = snip_old_tool_results(
            messages, max_chars=2000, preserve_last_n_messages=2,
            tool_output_token_budget=500)

        assert "chars snipped" in result[0].content
        assert result[1].content == "B" * 100
        assert result[2].content == "Hello"

    def test_recent_output_within_budget_is_kept_verbatim(self):
        messages = [
            MockMessage("1", "user", "go"),
            MockMessage("2", "tool", "A" * 8000),
        ]
        result = snip_old_tool_results(
            messages, max_chars=2000, preserve_last_n_messages=2,
            tool_output_token_budget=50000)

        assert result[1].content == "A" * 8000

    def test_budget_is_spent_newest_first(self):
        """The newest output survives; the older one pays for it."""
        messages = [
            MockMessage("old", "tool", "O" * 20000),
            MockMessage("new", "tool", "N" * 20000),
        ]
        result = snip_old_tool_results(
            messages, max_chars=2000, preserve_last_n_messages=10,
            tool_output_token_budget=estimate_tokens(
                [MockMessage("probe", "tool", "N" * 20000)]))

        assert result[1].content == "N" * 20000
        assert "chars snipped" in result[0].content

    def test_snipped_output_keeps_its_tail(self):
        content = "HEAD" + "x" * 20000 + "VERDICT-LINE"
        messages = [MockMessage("1", "tool", content)]
        result = snip_old_tool_results(
            messages, max_chars=2000, preserve_last_n_messages=0,
            tool_output_token_budget=1)

        assert result[0].content.endswith("VERDICT-LINE")
        assert result[0].content.startswith("HEAD")

    def test_offloads_full_output_and_points_at_it(self, tmp_path):
        content = "Z" * 20000
        messages = [MockMessage("msg-1", "tool", content)]
        result = snip_old_tool_results(
            messages, max_chars=2000, preserve_last_n_messages=0,
            tool_output_token_budget=1, offload_dir=str(tmp_path))

        offloaded = tmp_path / "msg-1.txt"
        assert offloaded.exists()
        assert offloaded.read_text() == content
        assert str(offloaded) in result[0].content

    def test_short_tool_message_unchanged(self):
        messages = [
            MockMessage("1", "tool", "A" * 100),
            MockMessage("2", "user", "Hello"),
        ]
        result = snip_old_tool_results(messages, tool_output_token_budget=1)

        assert result[0].content == "A" * 100

    def test_non_tool_message_unchanged(self):
        messages = [
            MockMessage("1", "user", "Hello"),
            MockMessage("2", "assistant", "Hi!"),
        ]
        result = snip_old_tool_results(messages, tool_output_token_budget=1)

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
            scope_tokens=0, total_tokens=0, model_max_tokens=10000)

    def test_compact_when_scope_reaches_threshold(self):
        from nova.agent.compaction import compaction_threshold

        model_max_tokens = 200_000
        threshold = compaction_threshold(model_max_tokens)
        assert should_compact(
            scope_tokens=threshold,
            total_tokens=threshold,
            model_max_tokens=model_max_tokens,
        )

    def test_no_compact_below_threshold(self):
        from nova.agent.compaction import compaction_threshold

        model_max_tokens = 200_000
        threshold = compaction_threshold(model_max_tokens)
        assert not should_compact(
            scope_tokens=threshold - 1,
            total_tokens=threshold - 1,
            model_max_tokens=model_max_tokens,
        )

    def test_message_count_alone_never_triggers_compaction(self):
        """A long history of tiny messages must not compact a 1M window."""
        assert not should_compact(
            scope_tokens=5_000,
            total_tokens=5_000,
            model_max_tokens=1_000_000,
        )

    def test_hard_context_cap_forces_compaction_despite_small_scope(self):
        assert should_compact(
            scope_tokens=10,
            total_tokens=200_000,
            model_max_tokens=200_000,
        )

    def test_threshold_reserves_are_absolute_not_proportional(self):
        from nova.agent.compaction import compaction_threshold

        medium = compaction_threshold(128_000)
        large = compaction_threshold(1_000_000)
        assert 128_000 - medium == 1_000_000 - large == 24_000

    def test_small_windows_never_reserve_more_than_half(self):
        """A flat reserve would leave a 26k window compacting on every request."""
        from nova.agent.compaction import compaction_threshold

        for window in (6_826, 13_654, 26_666, 32_000):
            threshold = compaction_threshold(window)
            assert threshold == window - window // 2
            assert threshold >= window * 0.5


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


class StubSummaryProvider:
    """Minimal LLMProvider stand-in for compaction tests."""

    def __init__(self, summary: str = "compacted summary", fail: bool = False):
        self._summary = summary
        self._fail = fail
        self.calls = 0

    async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
        self.calls += 1
        if self._fail:
            raise RuntimeError("summarizer unavailable")
        from nova.llm.provider import Done
        return Done(content=self._summary)

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        raise NotImplementedError

    async def count_tokens(self, text: str, model: str = None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


async def _seed_compactable_session(db, session_id: str):
    from nova.session.manager import SessionContext

    session = SessionContext.create()
    session.id = session_id
    await db.save_session(session)
    await db.add_message(session_id, "user", "first question " + "x" * 4000)
    await db.add_message(session_id, "assistant", "first answer " + "y" * 4000)
    await db.add_message(session_id, "user", "second question")
    await db.add_message(session_id, "assistant", "second answer")


@pytest.mark.asyncio
async def test_compact_writes_summary_and_marks_old_messages():
    from nova.db.sqlite_repository import SqliteRepository
    from nova.db.config import DatabaseConfig
    from nova.agent.compaction import compact

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "test-session-123"
        await _seed_compactable_session(db, session_id)
        llm = StubSummaryProvider("the compacted state")

        assert await compact(session_id, db, llm, "gemma4:26b", split_index=2) is True

        remaining = await db.get_messages(session_id)
        summaries = [m for m in remaining if m.summary == 1]
        assert len(summaries) == 1
        assert "Previous conversation summary" in summaries[0].content
        assert "the compacted state" in summaries[0].content
        assert llm.calls == 1

        session = await db.get_session(session_id)
        assert session["compacted_at"] is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_compact_aborts_without_writing_when_summary_fails():
    from nova.db.sqlite_repository import SqliteRepository
    from nova.db.config import DatabaseConfig
    from nova.agent.compaction import compact

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "test-session-fail"
        await _seed_compactable_session(db, session_id)
        before = await db.get_messages(session_id)
        llm = StubSummaryProvider(fail=True)

        assert await compact(session_id, db, llm, "gemma4:26b", split_index=2) is False

        after = await db.get_messages(session_id)
        assert [m.id for m in after] == [m.id for m in before]
        assert not [m for m in after if m.summary == 1]
        assert not [m for m in after if "Summary generation failed" in (m.content or "")]

        session = await db.get_session(session_id)
        assert session["compacted_at"] is None
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


class TestTokensSinceCompact:
    def test_counts_whole_history_before_the_first_compaction(self):
        from nova.agent.compaction import count_tokens_since_compact

        messages = [MockTimedMessage("1", "user", "x" * 400, time_created=100)]
        assert count_tokens_since_compact(messages, None) == estimate_tokens(messages)

    def test_counts_only_messages_created_after_compaction(self):
        from nova.agent.compaction import count_tokens_since_compact

        old = MockTimedMessage("1", "user", "x" * 4000, time_created=100)
        fresh = MockTimedMessage("2", "user", "y" * 40, time_created=300)
        scope = count_tokens_since_compact([old, fresh], 200)
        assert scope == estimate_tokens([fresh])
        assert scope < estimate_tokens([old, fresh])

    def test_carried_summary_prefix_does_not_force_repeated_compaction(self):
        """The summary plus preserved history must not consume the budget."""
        from nova.agent.compaction import count_tokens_since_compact, compaction_threshold

        model_max_tokens = 200_000
        carried = [
            MockTimedMessage("summary", "assistant", "s" * 900_000, time_created=100),
        ]
        fresh = MockTimedMessage("new", "user", "hello", time_created=9_000)
        history = carried + [fresh]

        scope = count_tokens_since_compact(history, 5_000)
        assert scope < compaction_threshold(model_max_tokens)
        # The soft budget is satisfied, yet the hard window cap still fires.
        assert should_compact(
            scope_tokens=scope,
            total_tokens=estimate_tokens(history),
            model_max_tokens=model_max_tokens,
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
    def _paired_history(self):
        return [
            MockTimedMessage("1", "user", "q1"),
            MockTimedMessage("2", "assistant", "a1"),
            MockTimedMessage("3", "user", "q2"),
            MockTimedMessage("4", "assistant", "", tool_calls=[{"id": "a"}]),
            MockTimedMessage("5", "tool", "r", tool_call_id="a"),
            MockTimedMessage("6", "assistant", "done"),
        ]

    def test_split_retreats_to_the_user_turn_boundary(self):
        from nova.agent.compaction import _retreat_to_safe_split

        history = self._paired_history()
        for candidate in (2, 3, 4, 5):
            assert _retreat_to_safe_split(history, candidate) == 2

    def test_split_never_separates_assistant_from_its_tool_response(self):
        from nova.agent.compaction import _retreat_to_safe_split

        history = self._paired_history()
        split = _retreat_to_safe_split(history, 4)
        recent = history[split:]
        declared = {
            call["id"]
            for message in recent
            if message.role == "assistant"
            for call in (message.tool_calls or [])
        }
        answered = {
            message.tool_call_id
            for message in recent
            if message.role == "tool" and message.tool_call_id
        }
        assert answered <= declared
        assert recent[0].role == "user"
        assert recent

    def test_trailing_tool_messages_do_not_empty_the_recent_portion(self):
        from nova.agent.compaction import _retreat_to_safe_split

        history = [
            MockTimedMessage("1", "user", "q"),
            MockTimedMessage("2", "assistant", "", tool_calls=[{"id": "a"}]),
            MockTimedMessage("3", "tool", "r1", tool_call_id="a"),
            MockTimedMessage("4", "tool", "r2", tool_call_id="a"),
        ]
        for candidate in (2, 3, 4):
            split = _retreat_to_safe_split(history, candidate)
            assert split == 0, "an unsplittable history must report 0, not consume everything"

    def test_zero_split_is_untouched(self):
        from nova.agent.compaction import _retreat_to_safe_split

        history = [MockTimedMessage("1", "tool", "r", tool_call_id="a")]
        assert _retreat_to_safe_split(history, 0) == 0

    def test_find_split_point_returns_safe_boundary(self):
        history = [
            MockTimedMessage("1", "user", "x" * 4000),
            MockTimedMessage("2", "assistant", "", tool_calls=[{"id": "a"}]),
            MockTimedMessage("3", "tool", "y" * 4000, tool_call_id="a"),
            MockTimedMessage("4", "user", "z" * 40),
            MockTimedMessage("5", "assistant", "w" * 40),
        ]
        split = find_split_point(history, keep_ratio=0.3)
        assert split == 0 or _get_role(history[split]) == "user"


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


class MockUsageMessage(MockTimedMessage):
    def __init__(self, id, role, content, tokens_input=None, tokens_output=None,
                 tool_calls=None, tool_call_id=None, time_created=0):
        super().__init__(id, role, content, tool_calls, tool_call_id, time_created)
        self.tokens_input = tokens_input
        self.tokens_output = tokens_output


class TestUsageAnchoredEstimation:
    def test_falls_back_to_character_estimate_without_reported_usage(self):
        from nova.agent.compaction import estimate_context_tokens
        from nova.llm.tokenizer import estimate_messages_tokens

        messages = [MockUsageMessage("1", "user", "hello world")]
        assert estimate_context_tokens(messages) == estimate_messages_tokens(messages)

    def test_uses_reported_prompt_tokens_as_the_anchor(self):
        """The API count covers the system prompt and tool schemas we cannot see."""
        from nova.agent.compaction import estimate_context_tokens

        messages = [
            MockUsageMessage("1", "user", "tiny", time_created=1),
            MockUsageMessage("2", "assistant", "tiny", tokens_input=24_000,
                             tokens_output=100, time_created=2),
        ]
        assert estimate_context_tokens(messages) == 24_100

    def test_adds_only_messages_appended_after_the_anchor(self):
        from nova.agent.compaction import estimate_context_tokens
        from nova.llm.tokenizer import estimate_messages_tokens

        appended = MockUsageMessage("3", "user", "x" * 4000, time_created=3)
        messages = [
            MockUsageMessage("1", "user", "tiny", time_created=1),
            MockUsageMessage("2", "assistant", "tiny", tokens_input=24_000,
                             tokens_output=100, time_created=2),
            appended,
        ]
        expected = 24_100 + estimate_messages_tokens([appended])
        assert estimate_context_tokens(messages) == expected

    def test_latest_anchor_wins(self):
        from nova.agent.compaction import estimate_context_tokens

        messages = [
            MockUsageMessage("1", "assistant", "a", tokens_input=1_000,
                             tokens_output=10, time_created=1),
            MockUsageMessage("2", "assistant", "b", tokens_input=50_000,
                             tokens_output=20, time_created=2),
        ]
        assert estimate_context_tokens(messages) == 50_020

    def test_estimate_stays_stable_while_history_grows_without_new_usage(self):
        """A character-only estimate would drift; the anchor keeps the base exact."""
        from nova.agent.compaction import estimate_context_tokens

        anchor = MockUsageMessage("2", "assistant", "b", tokens_input=100_000,
                                  tokens_output=50, time_created=2)
        assert estimate_context_tokens([anchor]) == 100_050

    def test_relative_measures_never_use_the_anchor(self):
        """Split ratios and budgets compare messages with each other.

        Anchoring a subset on an API total would make it weigh as much as the
        whole prompt: the split target would become unreachable and compaction
        would silently stop happening.
        """
        from nova.llm.tokenizer import estimate_messages_tokens

        anchored = MockUsageMessage("1", "assistant", "b", tokens_input=500_000,
                                    tokens_output=10, time_created=1)
        assert estimate_tokens([anchored]) == estimate_messages_tokens([anchored])
        assert estimate_tokens([anchored]) < 1_000

    def test_split_point_still_found_when_history_carries_usage(self):
        history = [
            MockUsageMessage("1", "user", "x" * 8000, time_created=1),
            MockUsageMessage("2", "assistant", "y" * 8000, tokens_input=500_000,
                             tokens_output=2_000, time_created=2),
            MockUsageMessage("3", "user", "z" * 8000, time_created=3),
            MockUsageMessage("4", "assistant", "w" * 8000, time_created=4),
        ]
        assert find_split_point(history, keep_ratio=0.3) > 0

    def test_scope_growth_excludes_the_carried_prefix_even_with_usage(self):
        from nova.agent.compaction import count_tokens_since_compact

        carried = MockUsageMessage("1", "assistant", "s" * 4000,
                                   tokens_input=500_000, tokens_output=100,
                                   time_created=100)
        fresh = MockUsageMessage("2", "user", "hi", time_created=9_000)
        scope = count_tokens_since_compact([carried, fresh], 5_000)
        assert scope == estimate_tokens([fresh])
        assert scope < 100


class TestCompactionSummaryContract:
    @pytest.mark.asyncio
    async def test_summary_message_carries_a_continuation_instruction(self):
        from nova.db.sqlite_repository import SqliteRepository
        from nova.db.config import DatabaseConfig
        from nova.agent.compaction import compact, CONTINUATION_INSTRUCTION

        db = SqliteRepository(DatabaseConfig(path=":memory:"))
        await db.connect()
        try:
            session_id = "continuation-session"
            await _seed_compactable_session(db, session_id)
            await compact(session_id, db, StubSummaryProvider("state"),
                          "gemma4:26b", split_index=2)

            summaries = [m for m in await db.get_messages(session_id) if m.summary == 1]
            assert CONTINUATION_INSTRUCTION in summaries[0].content
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_prompt_asks_to_fold_in_a_previous_summary(self):
        from nova.db.sqlite_repository import SqliteRepository
        from nova.db.config import DatabaseConfig
        from nova.agent.compaction import compact, PREVIOUS_SUMMARY_ANCHOR

        class PromptCapturingProvider(StubSummaryProvider):
            def __init__(self):
                super().__init__("second-generation summary")
                self.prompt = ""

            async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
                self.prompt = messages[0]["content"]
                return await super().chat(messages, model, stream, tools, **kwargs)

        db = SqliteRepository(DatabaseConfig(path=":memory:"))
        await db.connect()
        try:
            session_id = "second-compaction"
            await _seed_compactable_session(db, session_id)
            await db.add_message(session_id, "assistant",
                                 "[Previous conversation summary]\nolder state",
                                 summary=True)
            await db.add_message(session_id, "user", "third question")
            await db.add_message(session_id, "assistant", "third answer")
            messages = await db.get_messages(session_id)
            summary_index = next(
                index for index, message in enumerate(messages) if message.summary == 1)
            llm = PromptCapturingProvider()

            await compact(session_id, db, llm, "gemma4:26b",
                          messages=messages, split_index=summary_index + 1)

            assert PREVIOUS_SUMMARY_ANCHOR in llm.prompt
            assert "Do not call any tool" in llm.prompt
        finally:
            await db.close()


class TestCompactionCircuitBreaker:
    def _agent(self):
        from nova import Agent, AgentConfig
        from nova.llm.provider import LLMProvider, Done

        class UnusedProvider(LLMProvider):
            async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
                return Done(content="")

            async def chat_stream(self, messages, model="m", tools=None, **kwargs):
                yield Done(content="")

            async def count_tokens(self, text, model=None):
                return len(text)

            def get_max_tokens(self, model):
                return 128000

        return Agent(config=AgentConfig(model="test-model"),
                     llm_provider=UnusedProvider())

    def test_allows_compaction_until_the_failure_limit(self):
        from nova.settings import get_settings

        agent = self._agent()
        limit = get_settings().compaction.max_consecutive_failures
        for _ in range(limit):
            assert agent._compaction.summarising_allowed()
            agent._compaction.consecutive_failures += 1
        assert not agent._compaction.summarising_allowed()

    def test_a_success_clears_the_failure_streak(self):
        agent = self._agent()
        agent._compaction.consecutive_failures = 99
        assert not agent._compaction.summarising_allowed()
        agent._compaction.consecutive_failures = 0
        assert agent._compaction.summarising_allowed()


class TestSummaryLifecycle:
    @pytest.mark.asyncio
    async def test_a_compacted_summary_leaves_the_active_history(self):
        """Summaries must not accumulate forever: once compacted they drop out."""
        from nova.db.sqlite_repository import SqliteRepository
        from nova.db.config import DatabaseConfig

        db = SqliteRepository(DatabaseConfig(path=":memory:"))
        await db.connect()
        try:
            session_id = "summary-lifecycle"
            await _seed_compactable_session(db, session_id)
            summary = await db.add_message(
                session_id, "assistant", "old summary", summary=True)

            active_before = await db.get_messages(session_id)
            assert summary.id in [m.id for m in active_before]

            await db.mark_messages_compacted_by_ids(session_id, [summary.id])

            active_after = await db.get_messages(session_id)
            assert summary.id not in [m.id for m in active_after]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_repeated_compaction_does_not_grow_the_summary_chain(self):
        from nova.db.sqlite_repository import SqliteRepository
        from nova.db.config import DatabaseConfig
        from nova.agent.compaction import compact

        db = SqliteRepository(DatabaseConfig(path=":memory:"))
        await db.connect()
        try:
            session_id = "repeated-compaction"
            await _seed_compactable_session(db, session_id)
            llm = StubSummaryProvider("generation-1")
            await compact(session_id, db, llm, "gemma4:26b", split_index=2)

            await db.add_message(session_id, "user", "next question")
            await db.add_message(session_id, "assistant", "next answer")
            messages = await db.get_messages(session_id)
            next_user_index = next(
                index for index, message in enumerate(messages)
                if message.role == "user" and message.content == "next question")

            llm._summary = "generation-2"
            await compact(session_id, db, llm, "gemma4:26b",
                          messages=messages, split_index=next_user_index)

            summaries = [m for m in await db.get_messages(session_id) if m.summary == 1]
            assert len(summaries) == 1, "only the newest summary stays active"
            assert "generation-2" in summaries[0].content
        finally:
            await db.close()


class TestInLoopCompaction:
    """Context pressure must be re-checked before every model call.

    One request can run many tool turns and each tool result can be arbitrarily
    large, so a request that started inside the window can overrun it halfway
    through. Checking only once per request left that gap unguarded.
    """

    @staticmethod
    def _provider(scripts):
        from nova.llm.provider import Done, LLMProvider

        class ScriptedProvider(LLMProvider):
            def __init__(self):
                self._scripts = scripts
                self._index = 0
                self.summary_calls = 0

            async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
                self.summary_calls += 1
                return Done(content="mid-request summary")

            async def chat_stream(self, messages, model="m", tools=None, **kwargs):
                script = self._scripts[min(self._index, len(self._scripts) - 1)]
                self._index += 1
                for item in script:
                    await asyncio.sleep(0)
                    yield item

            async def count_tokens(self, text, model=None):
                return len(text)

            def get_max_tokens(self, model):
                return 128000

        return ScriptedProvider()

    @staticmethod
    @contextlib.asynccontextmanager
    async def _isolated_store():
        """Fresh DB plus a fresh SessionManager.

        The session manager is a module singleton that caches its data source on
        first use. Swapping only ``database._db`` would leave message writes on
        the previous test's store while compaction wrote to the new one.
        """
        from nova.db.sqlite_repository import SqliteRepository
        from nova.db.config import DatabaseConfig
        from nova.db import database as db_module
        from nova.session import manager as session_manager

        database = SqliteRepository(DatabaseConfig(path=":memory:"))
        await database.connect()
        previous_db = db_module._db
        previous_manager = session_manager._manager
        db_module._db = database
        session_manager._manager = None
        try:
            yield database
        finally:
            await database.close()
            db_module._db = previous_db
            session_manager._manager = previous_manager

    @pytest.mark.asyncio
    async def test_layer1_trims_bulky_tool_output_mid_request(self):
        """The non-LLM layer is what saves a runaway tool loop, and it runs per turn."""
        from nova import Agent, AgentConfig
        from nova.agent.compaction import SNIP_MARKER
        from nova.agent.core import AgentEvent
        from nova.llm import ToolResult
        from nova.llm.provider import TextDelta, ToolCall

        async with self._isolated_store():
            provider = self._provider([
                [ToolCall(id="t1", name="bulky_tool", arguments="{}")],
                [ToolCall(id="t2", name="bulky_tool", arguments="{}")],
                [TextDelta(content="done")],
            ])
            agent = Agent(
                config=AgentConfig(model="test-model", max_iterations=5),
                llm_provider=provider,
            )

            async def bulky_tool() -> ToolResult:
                return ToolResult(success=True, content="B" * 400_000)

            agent.register_tool(bulky_tool, name="bulky_tool")

            session_id = None
            events = []
            async for event, data in agent.chat_stream("go"):
                events.append((event, data))
                if event == AgentEvent.SESSION:
                    session_id = data

            assert len([e for e, _ in events if e == AgentEvent.TURN_START]) >= 2

            stored = await agent.session.get_messages(session_id=session_id)
            tool_messages = [m for m in stored if m.role == "tool"]
            assert tool_messages, "the tool must have run"
            assert any(SNIP_MARKER in (m.content or "") for m in tool_messages), (
                "an oversized tool result must be trimmed during the request, "
                "not left to overrun the context window")
            assert provider.summary_calls == 0, (
                "Layer 1 alone was enough; no summarisation call should be spent")

    @pytest.mark.asyncio
    async def test_layer2_fires_mid_request_when_trimming_is_not_enough(self):
        """Assistant text cannot be trimmed by Layer 1, so Layer 2 must step in."""
        from nova import Agent, AgentConfig
        from nova.agent.core import AgentEvent
        from nova.llm import ToolResult
        from nova.llm.provider import TextDelta, ToolCall

        async with self._isolated_store():
            provider = self._provider([
                [TextDelta(content="first answer")],
                [TextDelta(content="X" * 400_000),
                 ToolCall(id="t1", name="tiny_tool", arguments="{}")],
                [TextDelta(content="done")],
            ])
            agent = Agent(
                config=AgentConfig(model="test-model", max_iterations=5),
                llm_provider=provider,
            )

            async def tiny_tool() -> ToolResult:
                return ToolResult(success=True, content="ok")

            agent.register_tool(tiny_tool, name="tiny_tool")

            session_id = None
            async for event, data in agent.chat_stream("first request"):
                if event == AgentEvent.SESSION:
                    session_id = data

            events = []
            async for event, data in agent.chat_stream("second request", session_id=session_id):
                events.append((event, data))

            assert len([e for e, _ in events if e == AgentEvent.TURN_START]) >= 2
            assert [e for e, _ in events if e == AgentEvent.COMPACTION_START], (
                "context that grew past the threshold inside the request must be "
                "compacted before the next model call")
            assert provider.summary_calls >= 1

    @pytest.mark.asyncio
    async def test_small_request_never_compacts(self):
        from nova import Agent, AgentConfig
        from nova.agent.core import AgentEvent
        from nova.llm import ToolResult
        from nova.llm.provider import TextDelta, ToolCall

        async with self._isolated_store():
            provider = self._provider([
                [ToolCall(id="t1", name="tiny_tool", arguments="{}")],
                [TextDelta(content="done")],
            ])
            agent = Agent(
                config=AgentConfig(model="test-model", max_iterations=5),
                llm_provider=provider,
            )

            async def tiny_tool() -> ToolResult:
                return ToolResult(success=True, content="ok")

            agent.register_tool(tiny_tool, name="tiny_tool")

            events = []
            async for event, data in agent.chat_stream("go"):
                events.append((event, data))

            assert not [e for e, _ in events if e == AgentEvent.COMPACTION_START]
            assert provider.summary_calls == 0

    @pytest.mark.asyncio
    async def test_open_breaker_skips_summarising_but_keeps_trimming(self):
        from nova import Agent, AgentConfig
        from nova.agent.compaction import SNIP_MARKER
        from nova.agent.core import AgentEvent
        from nova.llm import ToolResult
        from nova.llm.provider import TextDelta, ToolCall

        async with self._isolated_store():
            provider = self._provider([
                [ToolCall(id="t1", name="bulky_tool", arguments="{}")],
                [TextDelta(content="done")],
            ])
            agent = Agent(
                config=AgentConfig(model="test-model", max_iterations=5),
                llm_provider=provider,
            )
            agent._compaction.consecutive_failures = 99

            async def bulky_tool() -> ToolResult:
                return ToolResult(success=True, content="B" * 400_000)

            agent.register_tool(bulky_tool, name="bulky_tool")

            session_id = None
            events = []
            async for event, data in agent.chat_stream("go"):
                events.append((event, data))
                if event == AgentEvent.SESSION:
                    session_id = data

            assert not [e for e, _ in events if e == AgentEvent.COMPACTION_START]
            assert provider.summary_calls == 0

            stored = await agent.session.get_messages(session_id=session_id)
            tool_messages = [m for m in stored if m.role == "tool"]
            assert any(SNIP_MARKER in (m.content or "") for m in tool_messages), (
                "the breaker gates the model call, not the trimming that needs no model")


class TestContextWindowResolution:
    """Vendor windows differ by orders of magnitude, so guessing one number for
    every unknown model either starves large windows or overruns small ones."""

    def test_config_wins_over_every_builtin(self):
        from nova.llm.tokenizer import resolve_context_window

        mock_settings = MagicMock()
        mock_settings.providers = {
            "gw": MagicMock(models={"gpt-4": {"limit": {"context": 999_999}}}),
        }
        with patch("nova.settings.get_settings", return_value=mock_settings):
            window, source = resolve_context_window("gpt-4", "gw")
        assert (window, source) == (999_999, "config")

    def test_exact_entry_beats_the_family_pattern(self):
        from nova.llm.tokenizer import resolve_context_window

        window, source = resolve_context_window("gpt-4", "unconfigured")
        assert source == "exact"
        assert window == 8192, "gpt-4 is 8k even though the gpt family is larger"

    @pytest.mark.parametrize("model,expected", [
        ("gpt-4o", 128_000),
        ("gpt-4o-2024-08-06", 128_000),
        ("o3-mini", 200_000),
        ("claude-opus-5", 200_000),
        ("claude-fable-5", 1_000_000),
        ("gemini-3-flash", 1_048_576),
        ("gemini-1.5-pro", 2_097_152),
        ("muse-spark-1.2-contributor", 1_048_576),
        ("meta/muse-spark-1.2", 1_048_576),
        ("deepseek-v4-flash-free", 131_072),
        ("qwen3.7-plus", 131_072),
        ("kimi-k2-0905", 262_144),
        ("grok-4", 262_144),
        ("llama-4-scout", 1_048_576),
        ("gemma3:12b", 131_072),
    ])
    def test_family_patterns_cover_mainstream_models(self, model, expected):
        from nova.llm.tokenizer import resolve_context_window

        window, source = resolve_context_window(model, "unconfigured")
        assert window == expected
        assert source.startswith("family") or source == "exact"

    def test_one_million_variant_marker_is_honoured(self):
        from nova.llm.tokenizer import resolve_context_window

        window, source = resolve_context_window("claude-sonnet-4-6[1m]", "unconfigured")
        assert (window, source) == (1_000_000, "variant")

    def test_unknown_model_falls_back_and_says_so(self):
        from nova.llm.tokenizer import DEFAULT_CONTEXT_WINDOW, resolve_context_window

        window, source = resolve_context_window("no-such-model-9000", "unconfigured")
        assert (window, source) == (DEFAULT_CONTEXT_WINDOW, "default")

    def test_default_window_is_configurable(self):
        from nova.llm.tokenizer import resolve_context_window

        mock_settings = MagicMock()
        mock_settings.providers = {}
        mock_settings.compaction = MagicMock(default_context_window=64_000)
        with patch("nova.settings.get_settings", return_value=mock_settings):
            window, source = resolve_context_window("no-such-model-9000", "x")
        assert (window, source) == (64_000, "default")

    @pytest.mark.parametrize("raw,normalised", [
        ("meta/muse-spark-1.2", "muse-spark-1.2"),
        ("gemma4:26b", "gemma4"),
        ("deepseek-v4-flash-free", "deepseek-v4-flash"),
        ("claude-sonnet-4-6[1m]", "claude-sonnet-4-6"),
        ("gpt-4o-2024-08-06", "gpt-4o"),
        ("  GPT-4O  ", "gpt-4o"),
    ])
    def test_model_id_normalisation(self, raw, normalised):
        from nova.llm.tokenizer import normalise_model_id

        assert normalise_model_id(raw) == normalised

    def test_margin_is_applied_on_top_of_the_resolved_window(self):
        from nova.llm.tokenizer import SAFETY_MARGIN, get_context_limit_with_margin

        assert get_context_limit_with_margin("gemini-3-flash", "unconfigured") == int(
            1_048_576 / SAFETY_MARGIN)
