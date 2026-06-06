from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.text import Text as RichText
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
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
    AskUserWizard,
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

if TYPE_CHECKING:
    from nova.cli.protocols import ChatControllerProtocol


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
        border-bottom: solid $border-blurred;
        height: 1;
        padding-top: 1;
        margin-bottom: 1;
    }

    MarkdownTable {
        background: ansi_default;
    }

    MarkdownTableContent {
        background: ansi_default;
        keyline: thin $border-blurred;
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
        background: $background;
        border-left: tall $primary;
        dock: bottom;
        height: auto;
        padding: 0;
    }

    ChatTextArea {
        width: 1fr;
        height: 1;
        background: $background;
        color: $foreground;
        border: none;
        padding: 0;
        scrollbar-size: 0 0;
    }

    ChatTextArea:focus {
        border: none;
    }

    ChatTextArea > .text-area--scroll {
        background: $background;
    }

    ChatTextArea .text-area--gutter {
        display: none;
        background: $background;
    }

    ChatTextArea .text-area--cursor-line {
        background: $background;
    }

    ChatTextArea .text-area--cursor {
        background: $foreground;
        color: $background;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", show=False),
    ]

    def __init__(self, controller: ChatControllerProtocol, theme: str = "textual-dark") -> None:
        super().__init__()
        self._controller: ChatControllerProtocol = controller
        self.theme = theme
        self._streaming = False
        self._asking = False
        self._current_handler: StreamHandler | None = None

    def action_quit(self) -> None:
        self.exit()

    def key_escape(self) -> None:
        """Stop streaming when Escape is pressed, but only if no modal is active."""
        if self._asking:
            return
        if self._streaming:
            self._streaming = False
            self._controller.request_stop()
            self._current_handler = None

    # =====================================================
    # Compose / Mount
    # =====================================================

    def compose(self) -> ComposeResult:
        yield ScrollableContainer(id="message-container")
        yield CommandSuggestions(id="suggestions")
        with Vertical(id="composer"):
            with Horizontal(id="input-wrap"):
                yield ChatTextArea()
            yield StatusBar()

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
        # Don't steal focus from AskUserWizard on click
        if not self._asking:
            self.query_one(ChatTextArea).focus()

    def on_focus(self, event) -> None:
        # Don't force focus back to ChatTextArea while AskUserWizard is active
        if not self._asking and not isinstance(event.widget, ChatTextArea):
            self.query_one(ChatTextArea).focus()

    # =====================================================
    # Command Suggestions
    # =====================================================

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._update_suggestions()

    def _update_suggestions(self) -> None:
        text = self.query_one(ChatTextArea).text.strip()
        suggestions = self.query_one("#suggestions", CommandSuggestions)
        if text.startswith("/"):
            try:
                specs = self._controller.command_registry.specs
            except Exception:
                suggestions.visible = False
                return
            suggestions.update_suggestions(specs, text[1:])
        else:
            suggestions.visible = False

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

    async def _handle_message(self, text: str) -> None:
        container = self.query_one("#message-container")
        user_msg = UserMessage(text)
        await container.mount(user_msg)
        user_msg.scroll_visible()
        await self._run_stream(text)

    # =====================================================
    # Stream
    # =====================================================

    async def _run_stream(self, text: str) -> None:
        container = self.query_one("#message-container")
        handler = StreamHandler(container, self._controller,
                                status_bar=self.query_one(StatusBar))
        self._current_handler = handler
        self._streaming = True

        try:
            await handler.run(text)
        finally:
            await handler.finalize()

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

        widget = AskUserWizard(questions)
        self._asking = True
        await container.mount(widget)
        widget.scroll_visible()
        log.debug("AskUserWizard mounted with %d questions", len(questions))

    async def on_ask_user_wizard_submitted(
        self, event: AskUserWizard.Submitted
    ) -> None:
        """Fired when user submits answers in AskUserWizard."""
        answers = event.answers
        log.debug("AskUserWizard answers: %s", answers)

        await self.query_one(AskUserWizard).remove()
        self._asking = False
        self.query_one(ChatTextArea).focus()

        from nova.cli.ask_user import format_answers_for_llm
        answer_text = format_answers_for_llm(answers, event.questions)

        container = self.query_one("#message-container")
        user_msg = UserMessage(answer_text)
        container.mount(user_msg)
        user_msg.scroll_visible()
        await self._run_stream(answer_text)

    async def on_ask_user_wizard_dismissed(
        self, event: AskUserWizard.Dismissed
    ) -> None:
        if self.query_one_or_none(AskUserWizard):
            await self.query_one(AskUserWizard).remove()
        self._asking = False
        self.query_one(ChatTextArea).focus()

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

    def info(self, text: str) -> None:
        self.show_info(text)

    def error(self, text: str) -> None:
        self.show_error(text)

    def show_info(self, text: str) -> None:
        container = self.query_one("#message-container")
        container.mount(BannerMessage(text))

    def show_error(self, text: str) -> None:
        from nova.cli.theme_colors import get_theme_colors
        c = get_theme_colors(self)
        container = self.query_one("#message-container")
        container.mount(BannerMessage(RichText(text, style=f"bold {c.error}")))

    def show_user_message(self, content: str) -> None:
        container = self.query_one("#message-container")
        container.mount(UserMessage(content))

    def clear_screen(self) -> None:
        container = self.query_one("#message-container")
        container.remove_children()
        self._print_banner()

    def shutdown(self) -> None:
        self.exit()

    def print_history_transcript(self, history: list) -> None:
        self.show_history(history)

    def show_history(self, history: list) -> None:
        container = self.query_one("#message-container")
        container.remove_children()
        self._print_banner()
        loading = BannerMessage("Loading history...")
        container.mount(loading)

        async def _render() -> None:
            from nova.cli.tool_rendering import (
                format_tool_params,
                get_tool_description,
                parse_tool_arguments,
                render_tool_result,
                tool_palette_from_theme,
            )
            from nova.cli.theme_colors import get_theme_colors

            tool_palette = tool_palette_from_theme(get_theme_colors(self))

            pending_blocks: dict[str, tuple[str, ToolBlock]] = {}
            batch_size = 20
            mounted_count = 0

            async def mount_history_widget(widget) -> None:
                nonlocal mounted_count
                await container.mount(widget)
                mounted_count += 1
                if mounted_count % batch_size == 0:
                    await asyncio.sleep(0)

            try:
                for msg in history:
                    role = getattr(msg, "role", None)
                    content_val = getattr(msg, "content", None) or ""

                    if role == "user":
                        if content_val.strip():
                            await mount_history_widget(UserMessage(content_val))
                        continue

                    if role == "assistant":
                        rc = getattr(msg, "reasoning_content", None) or ""
                        tool_calls = getattr(msg, "tool_calls", None) or []

                        if content_val.strip():
                            await mount_history_widget(HistoryMessage(content_val, rc))

                        for tc in tool_calls:
                            if isinstance(tc, dict):
                                tc_name = tc.get("name", tc.get(
                                    "function", {}).get("name", "tool"))
                                tc_id = tc.get("id", "")
                                tc_args = tc.get("arguments", tc.get(
                                    "function", {}).get("arguments", "{}"))
                            else:
                                tc_name = getattr(tc, "name", "tool")
                                tc_id = getattr(tc, "id", "")
                                tc_args = getattr(tc, "arguments", "{}")

                            arguments = parse_tool_arguments(tc_args)
                            description = get_tool_description(tc_name, arguments, palette=tool_palette)
                            params = format_tool_params(tc_name, arguments)

                            block = ToolBlock(tc_name, description, params, show_right=False)
                            block.set_done()
                            await mount_history_widget(block)

                            if tc_id:
                                pending_blocks[tc_id] = (tc_name, block)

                        continue

                    if role == "tool":
                        tool_call_id = getattr(msg, "tool_call_id", None) or ""
                        if content_val.strip() and tool_call_id in pending_blocks:
                            tc_name, block = pending_blocks.pop(tool_call_id)
                            rendered = render_tool_result(tc_name, content_val, palette=tool_palette)
                            if tc_name and tc_name.lower() in ("edit", "write", "write_files"):
                                block.set_done(rendered or content_val)
                            else:
                                block.set_done()
                        continue

                    if role == "system" and content_val.strip():
                        await mount_history_widget(HistoryMessage(content_val, ""))
            finally:
                await loading.remove()

            container.scroll_end(animate=False)

        self.run_worker(_render())
