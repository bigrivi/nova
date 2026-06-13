from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nova.cli.chat_app import EVICT_BATCH, MAX_WINDOW_WIDGETS, ChatApp
from nova.cli.widgets import AssistantMessage


class _MockWidget:
    def __init__(self, evictable=True, tag=None):
        self._evictable = evictable
        if tag is not None:
            self._nova_history_message = tag
        self._removed = False

    async def remove(self):
        self._removed = True


class _MockContainer:
    def __init__(self, children):
        self.children = children
        self.virtual_size = SimpleNamespace(height=200)
        self.scroll_y = 100


class TestAssistantMessageFullText:
    def test_full_text_starts_empty(self):
        msg = AssistantMessage()
        assert msg.full_text == ""

    @pytest.mark.asyncio
    async def test_write_chunk_accumulates_full_text(self):
        msg = AssistantMessage()
        await msg.write_chunk("Hello")
        assert msg.full_text == "Hello"

    @pytest.mark.asyncio
    async def test_multiple_chunks_accumulate(self):
        msg = AssistantMessage()
        await msg.write_chunk("Hello")
        await msg.write_chunk(", ")
        await msg.write_chunk("world")
        await msg.write_chunk("!")
        assert msg.full_text == "Hello, world!"

    @pytest.mark.asyncio
    async def test_full_text_persists_after_finalize(self):
        msg = AssistantMessage()
        await msg.write_chunk("Final content")
        await msg.finalize()
        assert msg.full_text == "Final content"

    @pytest.mark.asyncio
    async def test_full_text_intact_with_newlines(self):
        msg = AssistantMessage()
        await msg.write_chunk("Line one\n")
        await msg.write_chunk("Line two\n")
        await msg.write_chunk("Line three")
        assert msg.full_text == "Line one\nLine two\nLine three"


class TestSessionMessageSimpleNamespace:
    def test_user_message_attributes(self):
        ns = SimpleNamespace(role="user", content="hello world")
        assert getattr(ns, "role", None) == "user"
        assert getattr(ns, "content", None) == "hello world"
        assert (getattr(ns, "tool_calls", None) or []) == []
        assert (getattr(ns, "reasoning_content", None) or "") == ""

    def test_assistant_message_attributes(self):
        ns = SimpleNamespace(role="assistant", content="hi there")
        assert getattr(ns, "role", None) == "assistant"
        assert getattr(ns, "content", None) == "hi there"
        assert (getattr(ns, "tool_calls", None) or []) == []
        assert (getattr(ns, "reasoning_content", None) or "") == ""

    def test_getattr_id_fallback_to_id(self):
        ns = SimpleNamespace(role="user", content="test")
        msg_id = getattr(ns, "id", id(ns))
        assert msg_id == id(ns)

    def test_empty_content_handled(self):
        ns = SimpleNamespace(role="user", content="")
        content = getattr(ns, "content", None) or ""
        assert content == ""


class TestEvictTopIfNeeded:
    @pytest.fixture
    def app(self):
        app = ChatApp.__new__(ChatApp)
        app._older_history = []
        app._loading_history = False
        app._is_at_bottom = lambda c=None: True
        app._is_evictable = lambda c: getattr(c, "_evictable", True)
        app._after_refresh = AsyncMock()
        return app

    def _make_children(self, count, *, tag=True):
        """Build evictable children, each optionally tagged."""
        return [
            _MockWidget(tag=SimpleNamespace(role="user", content=f"msg{i}") if tag else None)
            for i in range(count)
        ]

    @pytest.mark.asyncio
    async def test_tagged_widgets_saved_to_older_history(self, app):
        children = self._make_children(MAX_WINDOW_WIDGETS + EVICT_BATCH)
        container = _MockContainer(children)

        app._older_history = []
        await app._evict_top_if_needed(container, force=True)

        assert len(app._older_history) == EVICT_BATCH
        assert app._older_history[0].content == "msg0"
        assert app._older_history[-1].content == f"msg{EVICT_BATCH - 1}"

    @pytest.mark.asyncio
    async def test_tagged_widgets_removed_from_container(self, app):
        children = self._make_children(MAX_WINDOW_WIDGETS + EVICT_BATCH)
        container = _MockContainer(children)

        await app._evict_top_if_needed(container, force=True)

        assert all(c._removed for c in children[:EVICT_BATCH])
        assert not any(c._removed for c in children[EVICT_BATCH:])

    @pytest.mark.asyncio
    async def test_untagged_widgets_dropped_without_saving(self, app):
        untagged = self._make_children(EVICT_BATCH, tag=False)
        tagged = self._make_children(MAX_WINDOW_WIDGETS, tag=True)
        children = untagged + tagged
        container = _MockContainer(children)

        app._older_history = []
        await app._evict_top_if_needed(container, force=True)

        assert len(app._older_history) == 0

    @pytest.mark.asyncio
    async def test_non_evictable_widgets_skipped(self, app):
        evictable = [
            _MockWidget(tag=SimpleNamespace(role="user", content=f"msg{i}"))
            for i in range(MAX_WINDOW_WIDGETS + EVICT_BATCH)
        ]
        non_evictable = _MockWidget(evictable=False, tag=SimpleNamespace(role="banner", content="skip"))
        children = [non_evictable] + evictable
        container = _MockContainer(children)

        app._older_history = []
        await app._evict_top_if_needed(container, force=True)

        assert not non_evictable._removed
        assert all(c._removed for c in evictable[:EVICT_BATCH])
        assert not any(c._removed for c in evictable[EVICT_BATCH:])

    @pytest.mark.asyncio
    async def test_no_eviction_below_max_widgets(self, app):
        children = self._make_children(MAX_WINDOW_WIDGETS, tag=True)
        container = _MockContainer(children)

        app._older_history = []
        await app._evict_top_if_needed(container, force=True)

        assert len(app._older_history) == 0
        assert not any(c._removed for c in children)

    @pytest.mark.asyncio
    async def test_eviction_limited_to_evict_batch(self, app):
        total = MAX_WINDOW_WIDGETS + EVICT_BATCH + 10
        children = [_MockWidget(tag=SimpleNamespace(role="user", content=f"msg{i}"))
                    for i in range(total)]
        container = _MockContainer(children)

        app._older_history = []
        await app._evict_top_if_needed(container, force=True)

        assert len(app._older_history) == EVICT_BATCH

    @pytest.mark.asyncio
    async def test_dedup_same_message_not_saved_twice(self, app):
        shared_msg = SimpleNamespace(role="user", content="dup")
        pad = self._make_children(MAX_WINDOW_WIDGETS, tag=True)
        children = [
            _MockWidget(tag=shared_msg),
            _MockWidget(tag=shared_msg),
        ] + pad
        container = _MockContainer(children)

        app._older_history = []
        await app._evict_top_if_needed(container, force=True)

        assert len(app._older_history) == EVICT_BATCH - 1
        assert app._older_history[0].content == "dup"

    @pytest.mark.asyncio
    async def test_evicted_messages_prepended_to_older_history(self, app):
        existing = [SimpleNamespace(role="assistant", content="existing")]
        app._older_history = list(existing)

        new_msg = SimpleNamespace(role="user", content="new")
        pad = self._make_children(MAX_WINDOW_WIDGETS, tag=True)
        children = [_MockWidget(tag=new_msg)] + pad
        container = _MockContainer(children)

        await app._evict_top_if_needed(container, force=True)

        assert len(app._older_history) == EVICT_BATCH + 1
        assert app._older_history[0].content == "new"
        assert app._older_history[-1].content == "existing"
