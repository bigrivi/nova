"""
Compaction Module Tests using pytest
"""

import asyncio
import contextlib
from unittest.mock import MagicMock, patch

import pytest

from nova.agent.compaction import (
    SUMMARY_MESSAGE_MAX_CHARS,
    CompactionError,
    _format_for_summary,
    _get_content,
    _get_msg_id,
    _get_role,
    _get_tool_call_id,
    _get_tool_call_ids,
    _get_tool_calls,
    estimate_context_tokens,
    estimate_tokens,
    evaluate_compaction,
    find_split_point,
    get_context_limit,
    should_compact,
    snip_old_tool_results,
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
        # "Hello" = 5 chars, 5/4 = 1
        assert tokens == 1

    def test_multiple_messages(self):
        messages = [
            MockMessage("1", "user", "Hello, how are you?"),  # 18 chars
            MockMessage("2", "assistant", "I'm doing well!"),  # 18 chars
            MockMessage("3", "user", "Can you help me?"),  # 17 chars
        ]
        tokens = estimate_tokens(messages)
        # 18/4=4, 18/4=4, 17/4=4, each message floored before summing
        assert tokens == 11

    def test_long_content(self):
        messages = [MockMessage("1", "user", "A" * 1000)]
        tokens = estimate_tokens(messages)
        # 1000 chars, 1000/4=250
        assert tokens == 250


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

        split = find_split_point(messages, keep_tokens=20)

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
        assert not should_compact(total_tokens=0, model_max_tokens=10000)

    def test_compact_when_total_reaches_the_threshold_not_the_window(self):
        """The trigger is the threshold, so the reserve stays free."""
        from nova.agent.compaction import compaction_threshold

        model_max_tokens = 200_000
        threshold = compaction_threshold(model_max_tokens)
        assert threshold < model_max_tokens, "the reserve must leave headroom"
        assert should_compact(
            total_tokens=threshold, model_max_tokens=model_max_tokens)

    def test_no_compact_below_threshold(self):
        from nova.agent.compaction import compaction_threshold

        model_max_tokens = 200_000
        threshold = compaction_threshold(model_max_tokens)
        assert not should_compact(
            total_tokens=threshold - 1, model_max_tokens=model_max_tokens)

    def test_message_count_alone_never_triggers_compaction(self):
        """A long history of tiny messages must not compact a 1M window."""
        assert not should_compact(total_tokens=5_000, model_max_tokens=1_000_000)

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


class TestResolveContextLimit:
    def test_with_provider_joint_lookup(self):
        """Provider + model joint lookup returns correct limit."""
        from nova.llm.tokenizer import resolve_context_limit

        mock_settings = MagicMock()
        mock_settings.providers = {
            "ollama": MagicMock(models={"gemma4:26b": {"limit": {"context": 32000}}}),
        }

        with patch("nova.settings.get_settings", return_value=mock_settings):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = resolve_context_limit("gemma4:26b", "ollama")
            assert result == 32000

    def test_with_provider_context_window_fallback(self):
        """Falls back to context_window when limit.context missing."""
        from nova.llm.tokenizer import resolve_context_limit

        mock_settings = MagicMock()
        mock_settings.providers = {
            "anthropic": MagicMock(models={"claude-3-sonnet": {"context_window": 200000}}),
        }

        with patch("nova.settings.get_settings", return_value=mock_settings):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = resolve_context_limit("claude-3-sonnet", "anthropic")
            assert result == 200000

    def test_unknown_provider_hardcoded_fallback(self):
        """Falls back to hardcoded defaults for unknown provider."""
        from nova.llm.tokenizer import resolve_context_limit

        mock_settings = MagicMock()
        mock_settings.providers = {}

        with patch("nova.settings.get_settings", return_value=mock_settings):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = resolve_context_limit("gpt-4o", "unknown")
            assert result == 128000

    def test_get_context_limit_passes_provider(self):
        """get_context_limit passes provider to resolve_context_limit."""
        mock_settings = MagicMock()
        mock_settings.providers = {
            "openai": MagicMock(models={"gpt-4o": {"limit": {"context": 200000}}}),
        }

        with patch("nova.settings.get_settings", return_value=mock_settings):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit("gpt-4o", "openai")
            assert result == 200000


class TestGetContextLimit:
    def test_gpt4o(self):
        assert get_context_limit("gpt-4o", "openai") == 128000

    def test_gemma(self):
        assert get_context_limit("gemma4:26b", "ollama") == 32000

    def test_unknown_model(self):
        assert get_context_limit("unknown-model", "openai") == 128000


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


class TestForcedCompaction:
    """A provider rejection outranks the token estimate.

    The estimate is what normally decides to compact, so it is also what can be
    wrong; when the provider refuses the request outright there is nothing left
    to weigh.
    """

    def _messages(self):
        return [
            MockMessage("1", "user", "short"),
            MockMessage("2", "assistant", "short"),
        ]

    def test_under_threshold_history_is_left_alone_by_default(self):
        plan = evaluate_compaction("s", self._messages(), None, "gpt-4o", "openai")
        assert plan.over_threshold is False
        assert plan.needs_compaction is False

    def test_force_plans_a_compaction_the_estimate_would_skip(self):
        plan = evaluate_compaction(
            "s", self._messages(), None, "gpt-4o", "openai", force=True)
        assert plan.over_threshold is True
        assert plan.needs_compaction is True
        assert plan.split_index > 0

    def test_force_still_needs_a_splittable_history(self):
        """Forcing must not manufacture a plan that cannot be executed.

        A single message has no boundary to cut on, so announcing a compaction
        here would strand the caller with a no-op it already reported.
        """
        plan = evaluate_compaction(
            "s", [MockMessage("1", "user", "only")], None, "gpt-4o", "openai",
            force=True,
        )
        assert plan.over_threshold is True
        assert plan.needs_compaction is False

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
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository
    from nova.session.manager import SessionContext
    from nova.session.models import MessageFilter

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

            async def fake_chat_stream(**_kwargs):
                from nova.llm.provider import Done

                yield Done(content="Summary of conversation")

            mock_llm = MagicMock()
            mock_llm.chat_stream = fake_chat_stream

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

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        from nova.llm.provider import Done, TextDelta

        self.calls += 1
        if self._fail:
            raise RuntimeError("summarizer unavailable")
        # Two chunks so the caller's accumulation is exercised, then the
        # terminal event a real provider would send.
        midpoint = len(self._summary) // 2
        yield TextDelta(content=self._summary[:midpoint])
        yield TextDelta(content=self._summary[midpoint:])
        yield Done(content=self._summary)

    async def count_tokens(self, text: str, model: str | None = None) -> int:
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
async def test_summary_failure_never_poisons_the_context():
    """A provider error aborts compaction; the error text must not be stored.

    The provider's message is non-empty, so the caller's "empty summary" guard
    only holds if generation returns "" rather than the error string — which is
    what the old ``str(response)`` fallback used to leak into the session.
    """
    from nova.agent.compaction import compact
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository

    class ErroringProvider(StubSummaryProvider):
        async def chat_stream(self, messages, model="m", tools=None, **kwargs):
            from nova.llm.provider import Error

            yield Error(message="HTTP 403: request rejected by gateway")

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "poison-check"
        await _seed_compactable_session(db, session_id)
        messages = await db.get_messages(session_id)

        with pytest.raises(CompactionError):
            await compact(
                session_id,
                db,
                ErroringProvider(),
                "gpt-4o",
                messages=messages,
                split_index=2,
            )

        active = await db.get_messages(session_id)
        assert not any(m.summary == 1 for m in active)
        assert not any("403" in (m.content or "") for m in active)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_summary_streams_to_the_caller():
    """The summary is streamed so the UI can show it while it is written."""
    from nova.agent.compaction import compact
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    chunks: list[str] = []
    try:
        session_id = "stream-check"
        await _seed_compactable_session(db, session_id)
        messages = await db.get_messages(session_id)

        compacted = await compact(
            session_id,
            db,
            StubSummaryProvider("folded history"),
            "gpt-4o",
            messages=messages,
            split_index=2,
            on_delta=chunks.append,
        )

        assert compacted is True
        assert "".join(chunks) == "folded history"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_summary_is_placed_at_the_compaction_boundary():
    """The summary stands in for the history it replaces, so it leads.

    Stamping it at insertion time put it after the kept messages, inverting the
    prompt's chronology, and left it outside the next split so a second summary
    piled up beside it. Session updated_at must still track insertion order.
    """
    from nova.agent.compaction import compact
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "boundary-check"
        await _seed_compactable_session(db, session_id)
        before = (await db.get_session(session_id))["updated_at"]

        assert await compact(
            session_id, db, StubSummaryProvider("folded"), "gpt-4o", split_index=2
        ) is True

        live = await db.get_messages(session_id)
        summaries = [m for m in live if m.summary == 1]
        assert len(summaries) == 1
        assert live[0].summary == 1, "the summary must lead the loaded history"
        assert live[0].time_created < live[1].time_created

        after = (await db.get_session(session_id))["updated_at"]
        assert after >= before, "the session must not move backwards in the sidebar"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_second_compaction_folds_the_previous_summary():
    """Exactly one summary survives, because the next split includes it."""
    from nova.agent.compaction import compact
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "fold-check"
        await _seed_compactable_session(db, session_id)
        assert await compact(
            session_id, db, StubSummaryProvider("first"), "gpt-4o", split_index=2
        ) is True

        await db.add_message(session_id, "user", "next question " + "z" * 4000)
        await db.add_message(session_id, "assistant", "next answer " + "w" * 4000)

        live = await db.get_messages(session_id)
        split = find_split_point(live, keep_tokens=1000)
        assert split > 0
        assert any(m.summary == 1 for m in live[:split]), (
            "the previous summary must fall inside the portion being folded in")

        assert await compact(
            session_id,
            db,
            StubSummaryProvider("second"),
            "gpt-4o",
            messages=live,
            split_index=split,
        ) is True

        final = await db.get_messages(session_id)
        assert len([m for m in final if m.summary == 1]) == 1
        assert final[0].summary == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_compact_writes_summary_and_marks_old_messages():
    from nova.agent.compaction import compact
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository

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
async def test_context_frames_drop_across_a_compaction(monkeypatch):
    """The reported context must fall when compaction rewrites the history.

    The stale-anchor bug made both frames report the same number: the
    pre-compaction tokens_input was still accepted after the compaction, so the
    post-compaction frame re-used it and the bar never moved.
    """
    from nova.agent.compaction import CompactionController
    from nova.agent.events import AgentEvent
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository
    from nova.session.manager import SessionContext

    monkeypatch.setattr(
        "nova.agent.compaction.get_context_limit", lambda model, provider: 4_000
    )

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "context-frames"
        session = SessionContext.create()
        session.id = session_id
        await db.save_session(session)

        # A bulky history whose assistant turn carries a pre-compaction
        # tokens_input, i.e. a usage figure that counts messages that are about
        # to be removed.
        for turn in range(4):
            await db.add_message(session_id, "user", f"q{turn} " + "x" * 8_000)
            await db.add_message(
                session_id,
                "assistant",
                f"a{turn} " + "y" * 8_000,
                tokens_input=200_000,
                tokens_output=50,
            )

        live_session = await db.get_session(session_id)
        messages = await db.get_messages(session_id)
        controller = CompactionController(model="gpt-4o", provider="openai")

        frames: list[dict] = []

        async def emit(event, payload):
            if event == AgentEvent.CONTEXT_UPDATE:
                frames.append(payload)

        result = controller.maybe_compact(
            messages=messages,
            session=live_session,
            db=db,
            llm=StubSummaryProvider("folded"),
            emit=emit,
        )
        async for _ in result:
            pass

        assert controller.compacted is True
        assert len(frames) == 2, "expected a frame before and after the compaction"
        before, after = frames
        assert after["used"] < before["used"], (
            f"context did not shrink: {before['used']} -> {after['used']}"
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_context_limit_is_the_compaction_threshold(monkeypatch):
    """The bar's denominator is the trigger point, not the raw window.

    Reporting against the raw window left the bar short of full at the very
    moment compaction fired, because the reserve is headroom the history can
    never use. The denominator must therefore be the same threshold the
    compaction decision uses.
    """
    from nova.agent.compaction import CompactionController, compaction_threshold
    from nova.agent.events import AgentEvent
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository
    from nova.session.manager import SessionContext

    window = 128_000
    monkeypatch.setattr(
        "nova.agent.compaction.get_context_limit", lambda model, provider: window
    )

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "context-limit"
        session = SessionContext.create()
        session.id = session_id
        await db.save_session(session)
        await db.add_message(session_id, "user", "hi")

        live_session = await db.get_session(session_id)
        messages = await db.get_messages(session_id)
        controller = CompactionController(model="gpt-4o", provider="openai")

        frames: list[dict] = []

        async def emit(event, payload):
            if event == AgentEvent.CONTEXT_UPDATE:
                frames.append(payload)

        async for _ in controller.maybe_compact(
            messages=messages,
            session=live_session,
            db=db,
            llm=StubSummaryProvider("x"),
            emit=emit,
        ):
            pass

        assert frames, "a context frame is emitted every turn"
        assert frames[0]["limit"] == compaction_threshold(window)
        assert frames[0]["limit"] < window, "the reserve must be excluded"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_the_shrink_comes_from_the_history_not_from_the_estimator(monkeypatch):
    """The reported drop must be a real reduction, measured like for like.

    The frame comparison above passes for the wrong reason when the estimator
    changes underneath it: a pre-compaction reading is anchored on the provider's
    own figure, while the post-compaction reading falls back to characters because
    no post-compaction call has happened yet. That gap alone is larger than the
    reduction, so the frame assertion would hold even if compaction freed nothing.

    Estimating both histories against the same ``compacted_at`` removes the
    estimator from the comparison, leaving only the difference in content.
    """
    from nova.agent.compaction import CompactionController, estimate_context_tokens
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository
    from nova.session.manager import SessionContext

    monkeypatch.setattr(
        "nova.agent.compaction.get_context_limit", lambda model, provider: 4_000
    )

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "shrink-is-real"
        session = SessionContext.create()
        session.id = session_id
        await db.save_session(session)

        for turn in range(6):
            await db.add_message(session_id, "user", f"q{turn} " + "x" * 8_000)
            await db.add_message(
                session_id, "assistant", f"a{turn} " + "y" * 8_000
            )

        live_session = await db.get_session(session_id)
        messages = await db.get_messages(session_id)
        before_history = estimate_context_tokens(messages, "gpt-4o")

        controller = CompactionController(model="gpt-4o", provider="openai")

        async def emit(event, payload):
            return None

        result = controller.maybe_compact(
            messages=messages,
            session=live_session,
            db=db,
            llm=StubSummaryProvider("folded"),
            emit=emit,
        )
        async for _ in result:
            pass
        assert controller.compacted is True

        fresh = await db.get_messages(session_id)
        compacted_at = live_session["compacted_at"]
        after_history = estimate_context_tokens(fresh, "gpt-4o", compacted_at)
        before_like_for_like = estimate_context_tokens(
            messages, "gpt-4o", compacted_at
        )

        removed = before_history - after_history
        assert removed > 0, "compaction freed nothing"
        assert after_history < before_like_for_like, (
            "the two histories are not comparable, so the frames prove nothing"
        )
        # Half the history, not merely "some of it": a split that folds in one
        # message still reduces the total, so a weaker bound would pass for a
        # compaction that freed almost nothing.
        assert removed >= before_history * 0.5, (
            f"compaction removed {removed} of {before_history} tokens, "
            "which is not a real reduction"
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_compact_aborts_without_writing_when_summary_fails():
    from nova.agent.compaction import compact
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "test-session-fail"
        await _seed_compactable_session(db, session_id)
        before = await db.get_messages(session_id)
        llm = StubSummaryProvider(fail=True)

        with pytest.raises(CompactionError):
            await compact(session_id, db, llm, "gemma4:26b", split_index=2)

        after = await db.get_messages(session_id)
        assert [m.id for m in after] == [m.id for m in before]
        assert not [m for m in after if m.summary == 1]
        assert not [m for m in after if "Summary generation failed" in (m.content or "")]

        session = await db.get_session(session_id)
        assert session["compacted_at"] is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a_transient_summary_failure_is_retried_once():
    """One retry absorbs a transient failure; the second attempt lands."""
    from nova.agent.compaction import compact
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository

    class FailOnceProvider(StubSummaryProvider):
        def __init__(self):
            super().__init__("recovered summary")
            self.attempts = 0

        async def chat_stream(self, messages, model="m", tools=None, **kwargs):
            from nova.llm.provider import Error

            self.attempts += 1
            if self.attempts == 1:
                yield Error(message="temporary upstream failure")
                return
            async for item in super().chat_stream(
                messages, model=model, tools=tools, **kwargs
            ):
                yield item

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "retry-session"
        await _seed_compactable_session(db, session_id)
        provider = FailOnceProvider()

        assert await compact(
            session_id, db, provider, "gemma4:26b", split_index=2) is True
        assert provider.attempts == 2, "the failed attempt is retried once"
        after = await db.get_messages(session_id)
        assert [m for m in after if m.summary == 1], "the retry's summary is stored"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prepare_and_run_compaction_with_real_llm():
    from nova.agent.compaction import prepare_compaction, run_compaction_plan
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository
    from nova.llm import OllamaProvider
    from nova.session.manager import SessionContext

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
    def __init__(
        self,
        id,
        role,
        content,
        tool_calls=None,
        tool_call_id=None,
        time_created=0,
        summary=0,
        tokens_input=0,
        tokens_output=0,
    ):
        super().__init__(id, role, content, tool_calls)
        self.tool_call_id = tool_call_id
        self.time_created = time_created
        self.summary = summary
        self.tokens_input = tokens_input
        self.tokens_output = tokens_output


class TestContextEstimateAnchor:
    def test_stale_anchor_from_before_compaction_is_ignored(self):
        """A pre-compaction tokens_input counts messages that were removed.

        Anchoring on it made the reported context (and therefore the
        compaction decision) stay at the pre-compaction size forever.
        """
        messages = [
            MockTimedMessage("1", "user", "old", time_created=100),
            MockTimedMessage(
                "2", "assistant", "old reply", time_created=200, tokens_input=250000
            ),
            MockTimedMessage("3", "assistant", "summary", time_created=300, summary=1),
            MockTimedMessage("4", "user", "new", time_created=400),
        ]
        assert estimate_context_tokens(messages, compacted_at=300) == estimate_tokens(
            messages
        )

    def test_surviving_messages_older_than_compaction_are_not_anchors(self):
        """The summary sits before the messages it replaced, so order cannot help.

        Ordering made every kept message look "newer than the summary", which
        handed the pre-compaction anchor straight back and left the reported size
        unchanged across a compaction.
        """
        messages = [
            MockTimedMessage("1", "assistant", "summary", time_created=100, summary=1),
            MockTimedMessage("2", "user", "kept", time_created=200),
            MockTimedMessage(
                "3",
                "assistant",
                "kept reply",
                time_created=300,
                tokens_input=25000,
                tokens_output=10,
            ),
            MockTimedMessage("4", "user", "new", time_created=400),
        ]
        assert estimate_context_tokens(messages, compacted_at=350) == estimate_tokens(
            messages
        )

    def test_anchor_recorded_after_compaction_is_used(self):
        messages = [
            MockTimedMessage("1", "assistant", "summary", time_created=100, summary=1),
            MockTimedMessage("2", "user", "new", time_created=200),
            MockTimedMessage(
                "3",
                "assistant",
                "reply",
                time_created=300,
                tokens_input=9000,
                tokens_output=10,
            ),
        ]
        value = estimate_context_tokens(messages, compacted_at=150)
        assert value >= 9000
        assert value < 20000

    def test_anchor_is_used_when_no_compaction_has_run(self):
        messages = [
            MockTimedMessage("1", "user", "hi", time_created=100),
            MockTimedMessage(
                "2", "assistant", "reply", time_created=200, tokens_input=5000
            ),
        ]
        assert estimate_context_tokens(messages) >= 5000


class TestNoRepeatedCompaction:
    @pytest.mark.asyncio
    async def test_a_small_window_does_not_recompact_on_the_next_turn(self, monkeypatch):
        """After a compaction the kept portion must fall below the threshold.

        Capping the kept budget at half the threshold is what stops the total
        from staying over it, which would otherwise compact again every turn.
        """
        from nova.agent.compaction import CompactionController
        from nova.db.config import DatabaseConfig
        from nova.db.sqlite_repository import SqliteRepository
        from nova.session.manager import SessionContext

        monkeypatch.setattr(
            "nova.agent.compaction.get_context_limit", lambda model, provider: 8_000)

        db = SqliteRepository(DatabaseConfig(path=":memory:"))
        await db.connect()
        try:
            session_id = "small-window"
            session = SessionContext.create()
            session.id = session_id
            await db.save_session(session)
            for turn in range(4):
                await db.add_message(session_id, "user", f"q{turn} " + "x" * 4_000)
                await db.add_message(session_id, "assistant", f"a{turn} " + "y" * 4_000)

            controller = CompactionController(model="gpt-4o", provider="openai")

            async def emit(event, payload):
                return None

            live_session = await db.get_session(session_id)
            messages = await db.get_messages(session_id)
            async for _ in controller.maybe_compact(
                messages=messages, session=live_session, db=db,
                llm=StubSummaryProvider("folded"), emit=emit,
            ):
                pass
            assert controller.compacted is True, "the oversized history should compact"

            await db.add_message(session_id, "user", "next")
            live_session = await db.get_session(session_id)
            messages = await db.get_messages(session_id)
            assert await controller.plan(messages, live_session, db) is None, (
                "the compacted history must sit below the threshold")
        finally:
            await db.close()


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


class TestSafeBoundary:
    """The recent portion may begin anywhere except on a tool response.

    A tool response whose declaring assistant message sits in the compacted
    portion is an orphan, and the provider rejects the request.
    """

    def _paired_history(self):
        return [
            MockTimedMessage("1", "user", "q1"),
            MockTimedMessage("2", "assistant", "a1"),
            MockTimedMessage("3", "user", "q2"),
            MockTimedMessage("4", "assistant", "", tool_calls=[{"id": "a"}]),
            MockTimedMessage("5", "tool", "r", tool_call_id="a"),
            MockTimedMessage("6", "assistant", "done"),
        ]

    def test_boundary_steps_forward_past_a_tool_response(self):
        from nova.agent.compaction import _first_safe_boundary

        history = self._paired_history()
        assert _first_safe_boundary(history, 4) == 5
        assert _first_safe_boundary(history, 5) == 5

    def test_no_target_ever_lands_on_a_tool_response(self):
        from nova.agent.compaction import _first_safe_boundary

        history = self._paired_history()
        for target in range(len(history) + 2):
            split = _first_safe_boundary(history, target)
            assert split == 0 or history[split].role != "tool", target

    def test_an_all_tool_tail_falls_back_to_the_earliest_boundary(self):
        """The pairing constraint outranks the budget.

        Landing on the last message instead would leave the recent portion
        starting with a tool response, which the provider rejects.
        """
        from nova.agent.compaction import _first_safe_boundary

        history = [
            MockTimedMessage("1", "user", "q"),
            MockTimedMessage("2", "assistant", "", tool_calls=[{"id": "a"}]),
            MockTimedMessage("3", "tool", "r1", tool_call_id="a"),
            MockTimedMessage("4", "tool", "r2", tool_call_id="a"),
        ]
        split = _first_safe_boundary(history, 2)
        assert split == 1
        assert history[split].role != "tool"

    def test_a_history_of_only_tool_responses_has_no_boundary(self):
        from nova.agent.compaction import _first_safe_boundary

        history = [
            MockTimedMessage("1", "tool", "r1", tool_call_id="a"),
            MockTimedMessage("2", "tool", "r2", tool_call_id="a"),
        ]
        assert _first_safe_boundary(history, 1) == 0

    def test_retained_portion_keeps_assistant_tool_pairing(self):
        history = self._paired_history()
        split = find_split_point(history, keep_tokens=1)
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
        assert recent
        assert answered <= declared
        assert recent[0].role != "tool"

    def test_single_user_turn_is_still_compactable(self):
        """One prompt followed by an agentic run has no user boundary at all.

        The recent portion therefore starts mid-turn, which is fine: the prompt
        itself is summarised, so the model still learns what was asked.
        """
        history = [
            MockTimedMessage("1", "user", "q"),
            MockTimedMessage("2", "assistant", "", tool_calls=[{"id": "a"}]),
            MockTimedMessage("3", "tool", "r1", tool_call_id="a"),
            MockTimedMessage("4", "tool", "r2", tool_call_id="a"),
        ]
        split = find_split_point(history, keep_tokens=1)
        assert split > 0
        recent = history[split:]
        assert recent
        assert recent[0].role != "tool"


class TestKeepBudget:
    def test_a_history_within_budget_is_left_alone(self):
        """Nothing to gain, and compacting anyway would repeat on every call.

        A ratio could not produce this case; an absolute budget can, whenever the
        budget exceeds the history.
        """
        history = [
            MockTimedMessage("1", "user", "q"),
            MockTimedMessage("2", "assistant", "a"),
        ]
        assert find_split_point(history, keep_tokens=20000) == 0

    def test_forcing_overrides_the_budget_check(self):
        """A rejected request can be small and still not fit.

        When the fixed prompt rather than the history is what overflows, folding
        the history is the only remedy left, so the budget check must not block it.
        """
        history = [
            MockTimedMessage("1", "user", "q"),
            MockTimedMessage("2", "assistant", "a"),
        ]
        assert find_split_point(history, keep_tokens=20000, force=True) == 1

    def test_the_budget_bounds_what_is_kept(self):
        """Retention tracks the budget, up to the granularity of one message.

        The walk adds whole messages until it reaches the budget, so it can
        overshoot by the last message it added; snapping forward over a run of
        tool responses can add more. It must not overshoot without bound.
        """
        history = [
            MockTimedMessage(str(i), "user" if i % 2 == 0 else "assistant",
                             f"{i} " + "x" * 8000)
            for i in range(20)
        ]
        per_message = max(estimate_tokens([message]) for message in history)
        for budget in (2000, 8000, 20000):
            split = find_split_point(history, keep_tokens=budget)
            assert split > 0, budget
            kept = estimate_tokens(history[split:])
            assert kept <= budget + per_message, (
                f"budget {budget} kept {kept}, one message is {per_message}")

    def test_retention_does_not_grow_with_the_history(self):
        """The defect this replaces: a ratio made the floor rise with the bloat.

        One turn that dumped a large tool result left a permanently higher floor,
        because the retained portion was always a share of a history that had
        itself grown. Measured on real sessions, the share version kept up to
        4.4x its target; the budget keeps the same amount regardless.
        """
        def build(count: int):
            return [
                MockTimedMessage(str(i), "user" if i % 2 == 0 else "assistant",
                                 f"{i} " + "x" * 8000)
                for i in range(count)
            ]

        kept = []
        for count in (10, 20, 40):
            history = build(count)
            split = find_split_point(history, keep_tokens=8000)
            assert split > 0, count
            kept.append(estimate_tokens(history[split:]))

        assert max(kept) - min(kept) <= 2000, (
            f"retention moved with the history: {kept}")

    def test_a_dominant_first_message_is_still_split(self):
        """A first message that alone outweighs the budget must not block it."""
        history = [
            MockTimedMessage("1", "user", "x" * 40000),
            MockTimedMessage("2", "user", "short"),
            MockTimedMessage("3", "assistant", "short"),
        ]
        assert find_split_point(history, keep_tokens=4000) == 1

    def test_refuses_to_fold_summary_into_summary(self):
        """Compacting only summaries frees no context and would repeat forever."""
        history = [
            MockTimedMessage("1", "assistant", "earlier summary", summary=1),
            MockTimedMessage("2", "assistant", "", tool_calls=[{"id": "a"}]),
            MockTimedMessage("3", "tool", "r", tool_call_id="a"),
        ]
        assert find_split_point(history, keep_tokens=1) == 0


@pytest.mark.asyncio
async def test_chat_stream_loads_messages_once_per_request():
    """chat_stream owns the single message load; turn 1 reuses it, later turns reload."""
    from nova import Agent, AgentConfig
    from nova.agent.core import AgentEvent
    from nova.db import database as db_module
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository
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
        assert find_split_point(history, keep_tokens=100) > 0


class TestCompactionSummaryContract:
    @pytest.mark.asyncio
    async def test_summary_message_carries_a_continuation_instruction(self):
        from nova.agent.compaction import CONTINUATION_INSTRUCTION, compact
        from nova.db.config import DatabaseConfig
        from nova.db.sqlite_repository import SqliteRepository

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
        from nova.agent.compaction import PREVIOUS_SUMMARY_ANCHOR, compact
        from nova.db.config import DatabaseConfig
        from nova.db.sqlite_repository import SqliteRepository

        class PromptCapturingProvider(StubSummaryProvider):
            def __init__(self):
                super().__init__("second-generation summary")
                self.prompt = ""
                self.system = ""

            async def chat_stream(self, messages, model="m", tools=None, **kwargs):
                # messages[0] is the system prompt; the transcript is the user turn.
                self.system = messages[0].content
                self.prompt = messages[1].content
                async for event in super().chat_stream(
                    messages, model, tools, **kwargs
                ):
                    yield event

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
            # The "never call a tool" instruction lives in the system prompt now,
            # which is what shapes the request as an agent turn.
            assert "Do not call any tool" in llm.system
        finally:
            await db.close()


class TestCompactionCircuitBreaker:
    def _agent(self):
        from nova import Agent, AgentConfig
        from nova.llm.provider import Done, LLMProvider

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
        from nova.db.config import DatabaseConfig
        from nova.db.sqlite_repository import SqliteRepository

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
        from nova.agent.compaction import compact
        from nova.db.config import DatabaseConfig
        from nova.db.sqlite_repository import SqliteRepository

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
                # The same method serves both turn calls and the compaction
                # summary call; the summary is identified by its system prompt.
                from nova.agent.compaction import SUMMARY_SYSTEM_PROMPT
                from nova.llm.provider import TextDelta

                if any(
                    getattr(message, "content", None) == SUMMARY_SYSTEM_PROMPT
                    for message in messages
                ):
                    self.summary_calls += 1
                    yield TextDelta(content="mid-request summary")
                    return
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
        from nova.db import database as db_module
        from nova.db.config import DatabaseConfig
        from nova.db.sqlite_repository import SqliteRepository
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
                # Large enough to cross the threshold for an unknown model: the
                # default window is 128000 and the reserve leaves 104000, so
                # 500k ASCII characters is about 125k estimated tokens.
                [TextDelta(content="X" * 500_000),
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

    def test_the_window_is_reported_undivided(self):
        """The provider's own number, with no margin taken off it.

        The margin used to be subtracted here, which made compaction fire before
        the window was actually full. Shrinking a hard number does not make the
        provider more forgiving, and an anchored estimate is already exact.
        """
        from nova.llm.tokenizer import resolve_context_limit

        assert resolve_context_limit("gemini-3-flash", "unconfigured") == 1_048_576


# ---------------------------------------------------------------------------
# Invariant: compaction must never rewrite `reasoning_content` when
# `provider_meta` is present.
#
# Anthropic persists extended-thinking as two halves: the thinking text in
# `messages.reasoning_content` and the cryptographic signature in
# `messages.provider_meta` as {"thinking_signature": "..."}. On the next turn
# the provider recombines them into the block Anthropic demands back verbatim:
#
#     {"type": "thinking", "thinking": reasoning_content or "", "signature": signature}
#
# The signature is over the thinking text. If compaction ever trims or
# rewrites `reasoning_content` while leaving `provider_meta` intact, the block
# silently stops matching its signature and Anthropic returns 400. A truncated
# text still looks legitimate, so no guard at send time can catch it. These
# tests lock the current behaviour - Layer 1 only touches `tool` roles and
# Layer 2 never edits messages (it marks and appends) - and will fire if a
# future optimisation tries to trim bulky thinking text without handling the
# signature.
# ---------------------------------------------------------------------------


def test_snip_does_not_touch_reasoning_content_with_provider_meta():
    """Layer 1 must not trim reasoning_content when provider_meta is present.

    Builds a history with a bulky assistant thinking message (reasoning_content
    well over max_chars) alongside old tool outputs large enough to be snipped.
    After snip_old_tool_results the tool output must be trimmed (proving the
    trim ran) while the assistant's reasoning_content and provider_meta stay
    byte-for-byte identical.
    """
    from nova.agent.compaction import SNIP_MARKER, snip_old_tool_results

    class MockThinkingMessage(MockMessage):
        def __init__(
            self,
            id: str,
            role: str,
            content: str,
            tool_calls=None,
            reasoning_content=None,
            provider_meta=None,
        ):
            super().__init__(id, role, content, tool_calls)
            self.reasoning_content = reasoning_content
            self.provider_meta = provider_meta

    long_reasoning = "R" * 10000
    signature = "SIG123"
    assistant_message = MockThinkingMessage(
        "assistant-thinking",
        "assistant",
        "assistant text",
        reasoning_content=long_reasoning,
        provider_meta={"thinking_signature": signature},
    )
    original_reasoning = assistant_message.reasoning_content
    original_meta = dict(assistant_message.provider_meta)

    messages = [
        MockThinkingMessage("tool-old-1", "tool", "A" * 30000),
        MockThinkingMessage("tool-old-2", "tool", "B" * 30000),
        assistant_message,
        MockThinkingMessage("user-1", "user", "Hello"),
        MockThinkingMessage("tool-recent-large", "tool", "C" * 30000),
    ]

    result = snip_old_tool_results(
        messages,
        max_chars=2000,
        preserve_last_n_messages=0,
        tool_output_token_budget=1,
    )

    # Prove the fixture is not vacuous: at least one tool result was actually snipped.
    assert any(SNIP_MARKER in (m.content or "") for m in result if m.role == "tool"), (
        "expected at least one tool message to be snipped; "
        "check max_chars / preserve_last_n_messages / tool_output_token_budget"
    )
    # The assistant thinking message must be untouched.
    found = next(m for m in result if m.id == "assistant-thinking")
    assert found.reasoning_content == original_reasoning
    assert found.reasoning_content == "R" * 10000
    assert found.provider_meta == original_meta
    assert found.provider_meta == {"thinking_signature": "SIG123"}


@pytest.mark.asyncio
async def test_compact_does_not_touch_reasoning_content_with_provider_meta():
    """Layer 2 must not rewrite reasoning_content when provider_meta is present.

    Drives compact() over a history whose recent portion contains an assistant
    message carrying reasoning_content + provider_meta, then reads the messages
    back and asserts that message's reasoning_content and provider_meta are
    unchanged. Reuses the StubSummaryProvider harness from existing compact
    tests.
    """
    from nova.agent.compaction import compact
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository
    from nova.session.manager import SessionContext
    from nova.session.models import MessageFilter

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "test-compact-thinking-preserved"
        session = SessionContext.create()
        session.id = session_id
        await db.save_session(session)

        await db.add_message(session_id, "user", "first question " + "x" * 4000)
        await db.add_message(session_id, "assistant", "first answer " + "y" * 4000)
        await db.add_message(session_id, "user", "second question")
        thinking_text = "R" * 10000
        signature = "SIG123"
        thinking_message = await db.add_message(
            session_id,
            "assistant",
            "second answer",
            reasoning_content=thinking_text,
            provider_meta={"thinking_signature": signature},
        )
        await db.add_message(session_id, "user", "third question")
        await db.add_message(session_id, "assistant", "third answer")

        original_reasoning = thinking_message.reasoning_content
        original_meta = dict(thinking_message.provider_meta)

        llm = StubSummaryProvider("the compacted state")
        # split_index=2 keeps the thinking message in the recent (preserved) portion
        assert await compact(session_id, db, llm, "gemma4:26b", split_index=2) is True

        all_messages = await db.get_messages(session_id, MessageFilter(include_compacted=True))
        found = next(m for m in all_messages if m.id == thinking_message.id)
        assert found.reasoning_content == original_reasoning
        assert found.reasoning_content == thinking_text
        assert found.provider_meta == original_meta
        assert found.provider_meta == {"thinking_signature": signature}

        # The thinking message must still be active (not compacted away).
        active = await db.get_messages(session_id)
        assert thinking_message.id in [m.id for m in active]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_compaction_pipeline_never_rewrites_reasoning_content_when_provider_meta_present():
    """Generic guard: every message with a truthy provider_meta must keep its
    reasoning_content byte-for-byte identical after the compaction pipeline.

    Snapshots (id, reasoning_content, provider_meta) for all messages that
    carry provider_meta before, drives both Layer 1 (snip_old_tool_results with
    an aggressive budget that definitely trims tool output) and Layer 2
    (compact) and then asserts the snapshot still matches. This is the test
    that will fail if any future change adds thinking-trimming anywhere in the
    pipeline.
    """
    import copy

    from nova.agent.compaction import SNIP_MARKER, compact, snip_old_tool_results
    from nova.db.config import DatabaseConfig
    from nova.db.sqlite_repository import SqliteRepository
    from nova.session.manager import SessionContext
    from nova.session.models import MessageFilter

    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "test-generic-thinking-guard"
        session = SessionContext.create()
        session.id = session_id
        await db.save_session(session)

        # Build a history with two thinking messages (one that will fall into
        # the compacted prefix and one that stays recent) plus bulky tool
        # outputs that guarantee Layer 1 has something to trim.
        await db.add_message(session_id, "user", "start " + "x" * 4000)
        thinking_old_text = "R" * 10000
        thinking_old = await db.add_message(
            session_id,
            "assistant",
            "old thinking answer",
            reasoning_content=thinking_old_text,
            provider_meta={"thinking_signature": "SIG_OLD"},
        )
        await db.add_message(session_id, "tool", "A" * 30000, tool_call_id="call-old")
        await db.add_message(session_id, "user", "middle question")
        thinking_recent_text = "S" * 12000
        thinking_recent = await db.add_message(
            session_id,
            "assistant",
            "recent thinking answer",
            reasoning_content=thinking_recent_text,
            provider_meta={"thinking_signature": "SIG_RECENT"},
        )
        await db.add_message(session_id, "tool", "B" * 30000, tool_call_id="call-recent")
        await db.add_message(session_id, "user", "final question")
        await db.add_message(session_id, "assistant", "final answer")

        # Snapshot every message that carries a truthy provider_meta before.
        before_all = await db.get_messages(session_id, MessageFilter(include_compacted=True))
        snapshot = [
            (message.id, message.reasoning_content, copy.deepcopy(message.provider_meta))
            for message in before_all
            if message.provider_meta
        ]
        assert len(snapshot) == 2, "fixture must contain exactly two thinking messages for the guard"

        # Layer 1: run snip_old_tool_results over the in-memory history with a
        # budget that forces trimming, and verify the guard holds in-memory.
        messages_for_snip = await db.get_messages(session_id, MessageFilter(include_compacted=True))
        snip_old_tool_results(
            messages_for_snip,
            max_chars=2000,
            preserve_last_n_messages=0,
            tool_output_token_budget=1,
        )
        assert any(SNIP_MARKER in (m.content or "") for m in messages_for_snip if m.role == "tool"), (
            "generic guard fixture is vacuous: no tool output was snipped"
        )
        for message_id, expected_reasoning, expected_meta in snapshot:
            found = next(m for m in messages_for_snip if m.id == message_id)
            assert found.reasoning_content == expected_reasoning, (
                f"Layer 1 rewrote reasoning_content for {message_id}"
            )
            assert found.provider_meta == expected_meta, (
                f"Layer 1 rewrote provider_meta for {message_id}"
            )

        # Layer 2: compact via DB, keeping the recent thinking message in the
        # preserved tail (split_index=4 corresponds to the user message that
        # starts the recent portion).
        llm = StubSummaryProvider("guard summary")
        assert await compact(session_id, db, llm, "gemma4:26b", split_index=4) is True

        after_all = await db.get_messages(session_id, MessageFilter(include_compacted=True))
        for message_id, expected_reasoning, expected_meta in snapshot:
            found = next((m for m in after_all if m.id == message_id), None)
            assert found is not None, f"message {message_id} disappeared after compaction"
            assert found.reasoning_content == expected_reasoning, (
                f"reasoning_content for {message_id} was rewritten by compaction "
                f"(expected {len(expected_reasoning or '')} chars, got {len(found.reasoning_content or '')})"
            )
            assert found.provider_meta == expected_meta, (
                f"provider_meta for {message_id} was rewritten by compaction"
            )
    finally:
        await db.close()


class TestSummaryFoldingIsLossless:
    def test_a_previous_summary_is_not_truncated_when_recompacted(self):
        """Folding a prior summary into a new one must not clip it.

        The previous-summary anchor tells the summariser to carry every
        still-relevant fact forward. Truncating the summary to a fixed cap would
        drop exactly those facts, and the loss compounds with each compaction.
        """
        summary_text = "FACT-" + "x" * 3000 + "-TAIL-" + "y" * 2000
        messages = [
            MockTimedMessage("1", "assistant", summary_text,
                             time_created=100, summary=1),
            MockTimedMessage("2", "user", "ordinary follow-up", time_created=200),
        ]

        rendered = _format_for_summary(messages)

        assert summary_text in rendered, "the previous summary must survive whole"

    def test_an_ordinary_message_is_still_capped(self):
        """Ordinary messages keep a cap so one huge paste cannot dominate."""
        huge = "z" * (SUMMARY_MESSAGE_MAX_CHARS + 500)
        rendered = _format_for_summary(
            [MockTimedMessage("1", "tool", huge, time_created=1)])

        assert huge not in rendered
        assert huge[:SUMMARY_MESSAGE_MAX_CHARS] in rendered


class TestForcedCompactionBypassesBreaker:
    @pytest.mark.asyncio
    async def test_forced_plan_ignores_an_open_circuit_breaker(self, monkeypatch):
        """A provider rejection stays recoverable after auto-compaction tripped.

        The breaker still guards threshold-triggered auto-compaction, but a
        forced run is the only way the rejected request can succeed, so it
        bypasses the gate.
        """
        from nova.agent import compaction as compaction_module
        from nova.agent.compaction import CompactionController, CompactionPlan

        async def fake_prepare_compaction(session_id, messages, last_compacted_at,
                                          db, model="gpt-4o", provider="ollama",
                                          force=False):
            return CompactionPlan(
                session_id, 128000, 200000, len(messages),
                needs_compaction=True, split_index=3, over_threshold=True,
            )

        monkeypatch.setattr(
            compaction_module, "prepare_compaction", fake_prepare_compaction)

        controller = CompactionController(model="gpt-4o", provider="openai")
        controller.consecutive_failures = 99  # breaker open
        assert not controller.summarising_allowed()
        session = {"id": "s1", "compacted_at": None}

        forced = await controller.plan([], session, None, force=True)
        assert forced is not None, "a forced run must not be blocked by the breaker"

        auto = await controller.plan([], session, None, force=False)
        assert auto is None, "the breaker still guards threshold-triggered compaction"
