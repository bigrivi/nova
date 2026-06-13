from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.text import Text as RichText
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message as TextualMessage
from textual.widget import Widget
from textual.widgets import TextArea

from nova.cli.screens import (
    AgentCreateResult,
    AgentListScreen,
    CreateAgentScreen,
    DeleteAgentScreen,
    DeleteConfirmScreen,
    ModelSelectScreen,
    SessionSelectScreen,
    ThemeSelectScreen,
)
from nova.cli.stream_handler import StreamHandler
from nova.cli.ui import ModelGroup, ModelSelection, SessionSelection
from nova.cli.widgets import (
    AskUserQuestion,
    AssistantMessage,
    BannerMessage,
    ChatTextArea,
    CommandSuggestions,
    HistoryMessage,
    MessageState,
    StatusBar,
    ToolBlock,
    UserMessage,
)

log = logging.getLogger(__name__)


HISTORY_CHUNK = 50
MAX_WINDOW_WIDGETS = 50
EVICT_BATCH = 20
AT_BOTTOM_THRESHOLD = 4

if TYPE_CHECKING:
    from nova.cli.protocols import ChatControllerProtocol


def _split_history_window(history: list, initial_size: int = HISTORY_CHUNK) -> tuple[list, list]:
    if initial_size <= 0 or len(history) <= initial_size:
        return [], list(history)
    return list(history[:-initial_size]), list(history[-initial_size:])


class MessageContainer(ScrollableContainer):
    """Scrollable chat container that emits edge events for lazy history loading."""

    class ScrolledToTop(TextualMessage):
        pass

    class ScrolledToBottom(TextualMessage):
        pass


    def on_mouse_scroll_up(self, event) -> None:
        self.call_after_refresh(self._check_top)

    def on_mouse_scroll_down(self, event) -> None:
        self.call_after_refresh(self._check_bottom)

    def _check_top(self) -> None:
        if self.scroll_y <= 1:
            self.post_message(self.ScrolledToTop())

    def _check_bottom(self) -> None:
        if self.scroll_y + self.size.height >= self.virtual_size.height - AT_BOTTOM_THRESHOLD:
            self.post_message(self.ScrolledToBottom())


class ChatApp(App):

    CSS = """
    Screen {
        background: ansi_default;
    }

    #message-container {
        background: ansi_default;
        overflow-y: auto;
        padding: 1 0 0 0;

        scrollbar-gutter: stable;
        scrollbar-size: 1 1;

        scrollbar-color: $surface;
        scrollbar-color-hover: $primary;
        scrollbar-color-active: $primary;

        scrollbar-background: transparent;
    }

    Markdown {
        background: ansi_default;
        color: $foreground;
        padding: 0 2;
        margin: 0 0 1 0;
    }

    MarkdownH1, MarkdownH2, MarkdownH3, MarkdownH4, MarkdownH5, MarkdownH6 {
        color: $text-primary;
        background: ansi_default;
        text-style: bold;
    }

    MarkdownFence {
        background: ansi_default;
        color: $foreground;
        margin: 1 0;
    }

    MarkdownCode {
        background: ansi_default;
        color: $success;
    }

    MarkdownHorizontalRule {
        background: ansi_default;
        border-bottom: solid #666666;
        height: 1;
        padding-top: 1;
        margin-bottom: 1;
    }

    MarkdownTable {
        background: ansi_default;
    }

    MarkdownTableContent {
        background: ansi_default;
        keyline: thin #666666;
    }

    MarkdownTableContent > .header {
        background: ansi_default;
        color: $secondary;
        text-style: bold;
    }

    MarkdownTableContent > .cell {
        background: ansi_default;
        color: $foreground;
    }

    #input-wrap {
        height: 3;
        align: left middle;
        padding: 1 2;
        background: transparent;
    }

    #composer {
        background: $surface;
        border-left: tall $primary;
        dock: bottom;
        height: auto;
        padding: 0;
    }

    ChatTextArea {
        width: 1fr;
        height: 1;
        background: $surface;
        color: $foreground;
        border: none;
        padding: 0;
        scrollbar-size: 0 0;
    }

    ChatTextArea:focus {
        border: none;
    }

    ChatTextArea > .text-area--scroll {
        background: $surface;
    }

    ChatTextArea .text-area--gutter {
        display: none;
        background: $surface;
    }

    ChatTextArea .text-area--cursor-line {
        background: $surface;
    }

    ChatTextArea .text-area--cursor {
        background: $foreground;
        color: $surface;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", show=False),
        Binding("down", "suggestions_down", show=False, priority=True),
        Binding("up", "suggestions_up", show=False, priority=True),
        Binding("enter", "suggestions_select", show=False, priority=True),
    ]

    def __init__(self, controller: ChatControllerProtocol, theme: str = "textual-dark") -> None:
        super().__init__()
        self._controller: ChatControllerProtocol = controller
        self.theme = theme
        self._streaming = False
        self._asking = False
        self._current_handler: StreamHandler | None = None
        self._older_history: list = []
        self._loading_history = False


    def action_quit(self) -> None:
        self.exit()

    def key_escape(self) -> None:
        if self._asking:
            return
        if self._suggestions_visible():
            self._suggestions_dismiss()
            return
        if self._streaming:
            self._streaming = False
            self._controller.request_stop()
            self._current_handler = None

    # =====================================================
    # Compose / Mount
    # =====================================================

    def compose(self) -> ComposeResult:
        yield MessageContainer(id="message-container")
        with Vertical(id="composer"):
            with Horizontal(id="input-wrap"):
                yield ChatTextArea()
            yield StatusBar()
        yield CommandSuggestions(id="suggestions")

    def on_mount(self) -> None:
        self.query_one(ChatTextArea).focus()
        self._print_banner()
        self._update_status_bar()

    @property
    def command_specs(self):
        return self._controller.command_registry.specs

    # =====================================================
    # Status Bar
    # =====================================================

    def update_status_bar(self) -> None:
        self._update_status_bar()

    def current_theme_name(self) -> str:
        return str(self.theme)

    def available_theme_names(self) -> list[str]:
        return sorted(self.available_themes)

    def set_theme_name(self, theme: str) -> bool:
        if theme not in self.available_themes:
            return False
        self.theme = theme
        self.refresh_css(animate=False)
        self._update_status_bar()
        return True

    def _update_status_bar(self) -> None:
        try:
            status = self._controller.get_status()
            model = status.model_label
            provider = status.provider_label
        except Exception:
            model = provider = ""
        self.query_one(StatusBar).update_labels(model, provider)

    # =====================================================
    # Banner
    # =====================================================

    def _print_banner(self) -> None:
        try:
            status = self._controller.get_status()
            model = status.model_label
            provider = status.provider_label
            banner_text = self._controller.command_registry.banner_text()
        except Exception:
            model = provider = ""
            banner_text = ""
        container = self.query_one("#message-container")
        from nova.cli.theme_colors import get_theme_colors
        c = get_theme_colors(self)
        version_text = RichText.assemble(
            ("Nova CLI  v0.1.0", f"bold {c.secondary}"),
        )
        model_text = RichText.assemble(
            ("Model", c.text_disabled),
            ("   ", ""),
            (model, c.foreground),
        )
        provider_text = RichText.assemble(
            ("Provider", c.text_disabled),
            ("    ", ""),
            (provider, f"bold {c.warning}"),
        )
        banner_rich = RichText.assemble(
            version_text, ("\n\n", ""),
            model_text, ("\n", ""),
            provider_text, ("\n\n", ""),
            (banner_text, c.text_muted),
        )
        container.mount(BannerMessage(Panel(
            banner_rich,
            border_style=c.surface,
            padding=(1, 2),
        )))

    # =====================================================
    # Focus
    # =====================================================

    def on_click(self, event) -> None:
        # Don't steal focus from AskUserQuestion on click
        if not self._asking:
            self.query_one(ChatTextArea).focus()

    def on_focus(self, event) -> None:
        # Don't force focus back to ChatTextArea while AskUserQuestion is active
        if not self._asking and not isinstance(event.widget, ChatTextArea):
            self.query_one(ChatTextArea).focus()

    # =====================================================
    # Command Suggestions
    # =====================================================

    async def on_text_area_changed(self, event: TextArea.Changed) -> None:
        await self._update_suggestions()

    async def _update_suggestions(self) -> None:
        text = self.query_one(ChatTextArea).text.strip()
        suggestions = self.query_one("#suggestions", CommandSuggestions)
        if text.startswith("/"):
            try:
                specs = self._controller.command_registry.specs
            except Exception:
                suggestions.display = False
                return
            await suggestions.update_suggestions(specs, text[1:])
        else:
            suggestions.display = False

    def _suggestions_visible(self) -> bool:
        return self.query_one("#suggestions", CommandSuggestions).display

    def _suggestions_dismiss(self) -> None:
        self.query_one("#suggestions", CommandSuggestions).display = False

    def action_suggestions_down(self) -> None:
        if not self._suggestions_visible():
            raise SkipAction()
        self.query_one("#suggestions", CommandSuggestions).action_cursor_down()

    def action_suggestions_up(self) -> None:
        if not self._suggestions_visible():
            raise SkipAction()
        self.query_one("#suggestions", CommandSuggestions).action_cursor_up()

    def action_suggestions_select(self) -> None:
        if not self._suggestions_visible():
            raise SkipAction()
        suggestions = self.query_one("#suggestions", CommandSuggestions)
        item = suggestions.highlighted_child
        if item is None or not hasattr(item, 'data'):
            return
        spec = item.data
        text_area = self.query_one(ChatTextArea)
        text_area.text = spec.usage or f"/{spec.id}"
        suggestions.display = False
        self.handle_submit(text_area.text)
        text_area.clear()
        text_area.sync_height()

    # =====================================================
    # Submit
    # =====================================================

    def handle_submit(self, text: str) -> None:
        if self._streaming or self._asking:
            return
        self.run_worker(self._handle_submit_async(text), exclusive=True)

    async def _handle_submit_async(self, text: str) -> None:
        if text.startswith("/") and not text.startswith("//"):
            await self._dispatch_command(text)
        else:
            await self._handle_message(text)

    async def _dispatch_command(self, text: str) -> None:
        handled = await self._controller.command_dispatcher.dispatch(text)
        if not handled:
            self._show_error_plain(f"Unknown command: {text}")

    def _show_error_plain(self, text: str) -> None:
        from nova.cli.theme_colors import get_theme_colors
        c = get_theme_colors(self)
        container = self.query_one("#message-container")
        container.mount(BannerMessage(RichText(text, style=f"bold {c.error}")))
        self._request_scroll_end()

    async def _handle_message(self, text: str) -> None:
        container = self.query_one("#message-container")
        user_msg = UserMessage(text)
        user_msg._nova_history_message = SimpleNamespace(role="user", content=text)
        await container.mount(user_msg)
        self._request_scroll_end()
        await self._run_stream(text)
        await self._evict_top_if_needed(container, force=True)

    # =====================================================
    # Stream
    # =====================================================

    async def _run_stream(self, text: str) -> None:
        container = self.query_one("#message-container")
        handler = StreamHandler(container, self._controller,
                                status_bar=self.query_one(StatusBar),
                                request_scroll_end=self._request_scroll_end,
                                is_at_bottom=lambda: self._is_at_bottom(container))
        self._current_handler = handler
        self._streaming = True

        try:
            await handler.run(text)
        finally:
            await handler.finalize()

            for child in reversed(list(container.children)):
                if isinstance(child, AssistantMessage) and not hasattr(child, "_nova_history_message"):
                    child._nova_history_message = SimpleNamespace(role="assistant", content=child.full_text)
                    break

            if self._controller.pending_input:
                await self._handle_pending_ask_user()

            self._streaming = False
            self._current_handler = None

    # =====================================================
    # Ask User（inline Widget, non-Modal）
    # =====================================================

    async def _handle_pending_ask_user(self) -> None:
        content = self._controller.pending_input.get("content", "")
        self._controller.reset_pending_input()
        if not content:
            return

        from nova.cli.ask_user import parse_ask_user_payload

        questions = parse_ask_user_payload(content)
        container = self.query_one("#message-container")

        if not questions:
            from nova.cli.theme_colors import get_theme_colors
            c = get_theme_colors(self)
            container.mount(BannerMessage(
                RichText("Error: Invalid ask_user payload.",
                         style=f"bold {c.error}")
            ))
            return

        widget = AskUserQuestion(questions)
        self._asking = True
        await container.mount(widget)
        widget.scroll_visible()
        log.debug("AskUserQuestion mounted with %d questions", len(questions))

    async def on_ask_user_question_submitted(
        self, event: AskUserQuestion.Submitted
    ) -> None:
        """Fired when user submits answers in AskUserQuestion."""
        answers = event.answers
        log.debug("AskUserQuestion answers: %s", answers)

        await self.query_one(AskUserQuestion).remove()
        self._asking = False
        self.query_one(ChatTextArea).focus()

        from nova.cli.ask_user import format_answers_for_llm
        answer_text = format_answers_for_llm(answers, event.questions)

        container = self.query_one("#message-container")
        user_msg = UserMessage(answer_text)
        user_msg._nova_history_message = SimpleNamespace(role="user", content=answer_text)
        await container.mount(user_msg)
        self._request_scroll_end(force=True)
        await self._evict_top_if_needed(container, force=True)
        await self._run_stream(answer_text)

    async def on_ask_user_question_dismissed(
        self, event: AskUserQuestion.Dismissed
    ) -> None:
        if self.query_one_or_none(AskUserQuestion):
            await self.query_one(AskUserQuestion).remove()
        self._asking = False
        self.query_one(ChatTextArea).focus()

    # =====================================================
    # Message window / scrolling
    # =====================================================

    def _is_at_bottom(self, container=None) -> bool:
        container = container or self.query_one("#message-container")
        return (
            container.scroll_y + container.size.height
            >= container.virtual_size.height - AT_BOTTOM_THRESHOLD
        )

    def _request_scroll_end(self, *, force: bool = False) -> None:
        container = self.query_one("#message-container")
        if not force and not self._is_at_bottom(container):
            return
        container.scroll_end(animate=False)

    async def _after_refresh(self, container) -> None:
        loop = asyncio.get_running_loop()
        done = loop.create_future()

        def _complete() -> None:
            if not done.done():
                done.set_result(None)

        container.call_after_refresh(_complete)
        await done

    async def _load_older_history(self) -> None:
        if self._loading_history or not self._older_history:
            return
        self._loading_history = True
        try:
            container = self.query_one("#message-container")
            batch = self._older_history[-HISTORY_CHUNK:]
            self._older_history = self._older_history[:-HISTORY_CHUNK]
            height_before = container.virtual_size.height
            insert_before = self._first_message_child(container)
            pending_blocks: dict[str, tuple[str, ToolBlock]] = {}
            prepared: list[tuple[Widget, object]] = []
            for msg in batch:
                prepared.extend((widget, msg) for widget in self._build_history_widgets(msg, pending_blocks))
            for widget, msg in reversed(prepared):
                setattr(widget, "_nova_history_message", msg)
                if insert_before:
                    await container.mount(widget, before=insert_before)
                else:
                    await container.mount(widget)
                insert_before = widget
                await asyncio.sleep(0)
            await self._after_refresh(container)
            delta = container.virtual_size.height - height_before
            container.scroll_y += delta
        finally:
            self._loading_history = False

    def _first_message_child(self, container) -> Widget | None:
        for child in container.children:
            if not isinstance(child, BannerMessage):
                return child
        return None

    async def _evict_top_if_needed(self, container=None, *, force: bool = False) -> None:
        container = container or self.query_one("#message-container")
        if not force and not self._is_at_bottom(container):
            return
        children = [child for child in container.children if self._is_evictable(child)]
        if len(children) <= MAX_WINDOW_WIDGETS:
            return
        to_evict = children[:EVICT_BATCH]
        evicted_messages = []
        seen_message_ids = set()
        height_before = container.virtual_size.height
        for child in to_evict:
            msg = getattr(child, "_nova_history_message", None)
            msg_id = getattr(msg, "id", id(msg)) if msg is not None else None
            if msg is not None and msg_id not in seen_message_ids:
                evicted_messages.append(msg)
                seen_message_ids.add(msg_id)
            await child.remove()
            await asyncio.sleep(0)
        if evicted_messages:
            self._older_history = evicted_messages + self._older_history
        await self._after_refresh(container)
        delta = container.virtual_size.height - height_before
        container.scroll_y = max(0, container.scroll_y + delta)

    def _is_evictable(self, widget: Widget) -> bool:
        if isinstance(widget, (BannerMessage, AskUserQuestion)):
            return False
        if self._current_handler is not None and widget is self._current_handler.assistant:
            return False
        if isinstance(widget, ToolBlock) and getattr(widget, "_state", None) == "running":
            return False
        return True

    def _build_history_widgets(self, msg, pending_blocks: dict[str, tuple[str, ToolBlock]]) -> list[Widget]:
        from nova.cli.tool_rendering import (
            REGISTRY,
            parse_tool_arguments,
            tool_palette_from_theme,
        )
        from nova.cli.theme_colors import get_theme_colors

        widgets: list[Widget] = []
        role = getattr(msg, "role", None)
        content = getattr(msg, "content", None) or ""

        if role == "user":
            if content.strip():
                widgets.append(UserMessage(content))
            return widgets

        if role == "assistant":
            reasoning_content = getattr(msg, "reasoning_content", None) or ""
            reasoning_elapsed_ms = getattr(msg, "reasoning_elapsed_ms", None)
            tool_calls = getattr(msg, "tool_calls", None) or []
            if content.strip():
                widgets.append(HistoryMessage(content, reasoning_content, elapsed_ms=reasoning_elapsed_ms))
            for tc in tool_calls:
                if isinstance(tc, dict):
                    tc_name = tc.get("name", tc.get("function", {}).get("name", "tool"))
                    tc_id = tc.get("id", "")
                    tc_args = tc.get("arguments", tc.get("function", {}).get("arguments", "{}"))
                else:
                    tc_name = getattr(tc, "name", "tool")
                    tc_id = getattr(tc, "id", "")
                    tc_args = getattr(tc, "arguments", "{}")
                arguments = parse_tool_arguments(tc_args)
                renderer = REGISTRY.get(tc_name)
                description = renderer.summary(arguments) if renderer else tc_name
                tool_palette = tool_palette_from_theme(get_theme_colors(self))
                detail_lines = renderer.render_detail(arguments, tool_palette) if renderer and renderer.render_detail else []
                block = ToolBlock(tc_name, description, detail_lines=detail_lines, show_right=False, raw_args=arguments)
                block.set_done()
                widgets.append(block)
                if tc_id:
                    pending_blocks[tc_id] = (tc_name, block)
            return widgets

        if role == "tool":
            tool_call_id = getattr(msg, "tool_call_id", None) or ""
            if content.strip() and tool_call_id in pending_blocks:
                tc_name, block = pending_blocks.pop(tool_call_id)
                renderer = REGISTRY.get(tc_name)
                result_lines = None
                if renderer and renderer.on_result:
                    result_lines = renderer.on_result(content, block._palette())
                block.set_done(result_lines)
            return widgets

        if role == "system" and content.strip():
            widgets.append(HistoryMessage(content, ""))
        return widgets

    def on_message_container_scrolled_to_top(self, event: MessageContainer.ScrolledToTop) -> None:
        if not self._loading_history and self._older_history:
            self.run_worker(self._load_older_history())

    def on_message_container_scrolled_to_bottom(self, event: MessageContainer.ScrolledToBottom) -> None:
        container = self.query_one("#message-container")
        self.run_worker(self._evict_top_if_needed(container))

    # =====================================================
    # Cancel Stream (ESC)
    # =====================================================

    # =====================================================
    # UI Adapter interface (called by NovaCLI)
    # =====================================================

    async def prompt_model_selection(
        self,
        groups: list[ModelGroup],
        *,
        current_provider: str,
        current_model: str,
    ) -> ModelSelection | None:
        return await self.push_screen_wait(
            ModelSelectScreen(
                groups=groups,
                current_provider=current_provider,
                current_model=current_model,
            )
        )

    async def prompt_session_selection(
        self,
        sessions: list[dict],
        *,
        current_session_id: str | None,
    ) -> SessionSelection | None:
        return await self.push_screen_wait(
            SessionSelectScreen(
                sessions=sessions,
                current_session_id=current_session_id,
            )
        )

    async def prompt_theme_selection(
        self,
        themes: list[str],
        *,
        current_theme: str,
    ) -> str | None:
        return await self.push_screen_wait(
            ThemeSelectScreen(themes=themes, current_theme=current_theme)
        )

    async def prompt_agent_list(self, agents: list[dict]) -> None:
        from nova.db.database import ensure_db
        db = await ensure_db()
        parent_map = {}
        for agent in agents:
            key = agent.get("key", "")
            parents = await db.get_agent_parents(key)
            if parents:
                parent_map[key] = parents
        await self.push_screen_wait(AgentListScreen(agents=agents, parent_map=parent_map))

    async def prompt_create_agent(self) -> AgentCreateResult | None:
        from nova.db.database import ensure_db
        db = await ensure_db()
        agents = await db.list_agents()
        return await self.push_screen_wait(CreateAgentScreen(agents=agents))

    async def prompt_delete_agent(self, agents: list[dict]) -> str | None:
        return await self.push_screen_wait(DeleteAgentScreen(agents=agents))

    async def prompt_delete_confirm(self, agent_key: str, session_count: int) -> bool:
        return await self.push_screen_wait(DeleteConfirmScreen(agent_key=agent_key, session_count=session_count))

    async def prompt_child_status(
        self,
        child_sessions: list[dict],
        current_session_id: str | None,
    ) -> None:
        from rich.table import Table
        from rich.panel import Panel
        from nova.cli.theme_colors import get_theme_colors

        c = get_theme_colors(self)
        table = Table(
            title="Child Sessions",
            show_header=True,
            header_style=f"bold {c.secondary}",
            title_style=f"bold {c.secondary}",
        )
        table.add_column("ID", style=c.text_muted, width=12)
        table.add_column("Agent", style=c.success)
        table.add_column("Title", style=c.foreground)
        table.add_column("Messages", justify="right", style=c.warning)
        table.add_column("Created", style=c.text_muted)
        table.add_column("Updated", style=c.text_muted)

        if not child_sessions:
            container = self.query_one("#message-container")
            container.mount(BannerMessage(RichText("No child sessions.", style=c.text_muted)))
            self._request_scroll_end()
            return

        for session in child_sessions:
            raw_session_id = session.get("id", "")
            session_id = raw_session_id[:12]
            agent_key = session.get("agent_key", "")
            title = session.get("title", "Untitled")
            if len(title) > 30:
                title = title[:27] + "..."
            message_count = session.get("message_count", 0)

            import time
            created_at = session.get("created_at", 0)
            updated_at = session.get("updated_at", 0)
            created_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at / 1000)) if created_at else "-"
            updated_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(updated_at / 1000)) if updated_at else "-"

            row_style = f"bold {c.warning}" if raw_session_id == current_session_id else None
            table.add_row(session_id, agent_key, title, str(message_count), created_str, updated_str, style=row_style)

        container = self.query_one("#message-container")
        container.mount(BannerMessage(Panel(table, border_style=c.surface)))
        self._request_scroll_end()

    def info(self, text: str) -> None:
        self.show_info(text)

    def error(self, text: str) -> None:
        self.show_error(text)

    def show_info(self, text: str) -> None:
        container = self.query_one("#message-container")
        container.mount(BannerMessage(text))
        self._request_scroll_end()

    def show_error(self, text: str) -> None:
        from nova.cli.theme_colors import get_theme_colors
        c = get_theme_colors(self)
        container = self.query_one("#message-container")
        container.mount(BannerMessage(RichText(text, style=f"bold {c.error}")))
        self._request_scroll_end()

    def show_user_message(self, content: str) -> None:
        container = self.query_one("#message-container")
        container.mount(UserMessage(content))
        self._request_scroll_end()

    def clear_screen(self) -> None:
        container = self.query_one("#message-container")
        container.remove_children()
        self._older_history = []
        self._print_banner()

    def shutdown(self) -> None:
        self.exit()

    def show_history(self, history: list) -> None:
        container = self.query_one("#message-container")
        container.remove_children()
        self._print_banner()
        self._older_history, visible_history = _split_history_window(history)
        loading = BannerMessage("Loading history...")
        container.mount(loading)

        async def _render() -> None:
            pending_blocks: dict[str, tuple[str, ToolBlock]] = {}
            try:
                for msg in visible_history:
                    for widget in self._build_history_widgets(msg, pending_blocks):
                        setattr(widget, "_nova_history_message", msg)
                        await container.mount(widget)
            finally:
                await loading.remove()

            self._request_scroll_end(force=True)

        self.run_worker(_render())
