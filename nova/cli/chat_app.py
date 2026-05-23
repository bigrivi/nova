from __future__ import annotations

import logging

from rich.panel import Panel
from rich.text import Text as RichText
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import TextArea

from nova.cli.repl import NovaCLI
from nova.cli.screens import ModelSelectScreen, SessionSelectScreen
from nova.cli.stream_handler import StreamHandler
from nova.cli.ui import ModelGroup, ModelSelection, SessionSelection
from nova.cli.widgets import (
    AskUserWidget,
    AssistantMessage,
    BannerMessage,
    ChatTextArea,
    CommandSuggestions,
    HistoryMessage,
    MessageState,
    StatusBar,
    UserMessage,
)

log = logging.getLogger(__name__)


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

        scrollbar-color: #2a2b3d;
        scrollbar-color-hover: #4a9eff;
        scrollbar-color-active: #4a9eff;

        scrollbar-background: transparent;
    }

    Markdown {
        background: ansi_default;
        color: #c0caf5;
        padding: 0 2;
        margin: 0 0 1 0;
    }

    MarkdownH1, MarkdownH2, MarkdownH3 {
        color: #7aa2f7;
        background: ansi_default;
    }

    MarkdownFence {
        background: #1a1b26;
        color: #c0caf5;
        margin: 1 0;
    }

    MarkdownCode {
        background: #1a1b26;
        color: #9ece6a;
    }

    #input-wrap {
        height: 3;
        align: left middle;
        padding: 1 2;
        background: transparent;
    }

    #composer {
        background: #1a1b26;
        border-left: tall #4a9eff;
        dock: bottom;
        height: auto;
        padding: 0;
    }

    ChatTextArea {
        width: 1fr;
        height: 1;
        background: #1a1b26;
        color: #c0caf5;
        border: none;
        padding: 0;
        scrollbar-size: 0 0;
    }

    ChatTextArea:focus {
        border: none;
    }

    ChatTextArea > .text-area--scroll {
        background: #1a1b26;
    }

    ChatTextArea .text-area--gutter {
        display: none;
        background: #1a1b26;
    }

    ChatTextArea .text-area--cursor-line {
        background: #1a1b26;
    }

    ChatTextArea .text-area--cursor {
        background: #c0caf5;
        color: #1a1b26;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", show=False),
        Binding("escape", "cancel_stream", show=False, priority=True),
    ]

    def __init__(self, nova_cli: NovaCLI) -> None:
        super().__init__()
        self._cli: NovaCLI = nova_cli
        self._streaming = False
        self._asking = False
        self._current_handler: StreamHandler | None = None

    def action_quit(self) -> None:
        self.exit()

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

    # =====================================================
    # Status Bar
    # =====================================================

    def update_status_bar(self) -> None:
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        try:
            model = self._cli.current_model_label
            provider = self._cli.current_provider_label
        except Exception:
            model = provider = ""
        self.query_one(StatusBar).update_labels(model, provider)

    # =====================================================
    # Banner
    # =====================================================

    def _print_banner(self) -> None:
        try:
            model = self._cli.current_model_label
            provider = self._cli.current_provider_label
            banner_text = self._cli.command_registry.banner_text()
        except Exception:
            model = provider = ""
            banner_text = ""
        container = self.query_one("#message-container")
        container.mount(BannerMessage(Panel(
            RichText.from_markup(
                "[bold #7aa2f7]Nova CLI  v0.1.0[/]\n"
                "\n"
                f"[#444466]Model[/]   [#c0caf5]{model}[/]\n"
                f"[#444466]Provider[/]    [#e0af68]{provider}[/]\n"
                "\n"
                f"[#565f89]{banner_text}[/]"
            ),
            border_style="#2a2b3d",
            padding=(1, 2),
        )))

    # =====================================================
    # Focus
    # =====================================================

    def on_click(self, event) -> None:
        # Don't steal focus from AskUserWidget on click
        if not self._asking:
            self.query_one(ChatTextArea).focus()

    def on_focus(self, event) -> None:
        # Don't force focus back to ChatTextArea while AskUserWidget is active
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
                specs = self._cli.command_registry.specs
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
        handled = await self._cli.command_dispatcher.dispatch(text)
        if not handled:
            self._show_error_plain(f"Unknown command: {text}")

    def _show_error_plain(self, text: str) -> None:
        container = self.query_one("#message-container")
        container.mount(BannerMessage(RichText(text, style="bold #f7768e")))

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
        handler = StreamHandler(container, self._cli,
                                status_bar=self.query_one(StatusBar))
        self._current_handler = handler
        self._cli.reset_stop_requested()
        self._streaming = True

        try:
            await handler.run(text)
        finally:
            await handler.finalize()

            if self._cli.pending_input:
                await self._handle_pending_ask_user()

            self._streaming = False
            self._current_handler = None

    # =====================================================
    # Ask User（inline Widget, non-Modal）
    # =====================================================

    async def _handle_pending_ask_user(self) -> None:
        content = self._cli.pending_input.get("content", "")
        self._cli.reset_pending_input()
        if not content:
            return

        from nova.cli.history_render import (
            parse_ask_user_question,
            parse_options,
            render_question_prompt,
        )

        question = parse_ask_user_question(content)
        container = self.query_one("#message-container")

        if not question:
            container.mount(BannerMessage(
                RichText("Error: Invalid ask_user payload.",
                         style="bold #f7768e")
            ))
            return

        options = parse_options(content)

        if options:
            opts = [(o.label, o.description) for o in options]
            widget = AskUserWidget(
                header=question.get("header", ""),
                question=question.get("question", ""),
                options=opts,
            )
            self._asking = True
            await container.mount(widget)
            widget.scroll_visible()
            log.debug("AskUserWidget mounted with %d options", len(opts))
        else:
            # Plain text input: prompt user to type in the input area
            from nova.cli.history_render import render_question_prompt
            prompt_text = render_question_prompt(question)
            container.mount(BannerMessage(RichText.from_ansi(prompt_text)))
            container.mount(BannerMessage(
                "Type your response and press Enter to submit."))

    async def on_ask_user_widget_option_selected(
        self, event: AskUserWidget.OptionSelected
    ) -> None:
        """Fired when user selects an option in AskUserWidget."""
        answer = event.answer
        log.debug("AskUserWidget selection: %s", answer)

        # Remove widget and restore state
        await self.query_one(AskUserWidget).remove()
        self._asking = False
        self.query_one(ChatTextArea).focus()

        # Render user choice and continue streaming
        container = self.query_one("#message-container")
        user_msg = UserMessage(answer)
        container.mount(user_msg)
        user_msg.scroll_visible()
        await self._run_stream(answer)

    # =====================================================
    # Cancel Stream (ESC)
    # =====================================================

    def action_cancel_stream(self) -> None:
        if self._asking:
            return
        if not self._streaming:
            return
        self._streaming = False
        self._cli.request_stop()
        self._current_handler = None

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

    def info(self, text: str) -> None:
        self.show_info(text)

    def error(self, text: str) -> None:
        self.show_error(text)

    def show_info(self, text: str) -> None:
        container = self.query_one("#message-container")
        container.mount(BannerMessage(text))

    def show_error(self, text: str) -> None:
        container = self.query_one("#message-container")
        container.mount(BannerMessage(RichText(text, style="bold #f7768e")))

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

        async def _render() -> None:
            for msg in history:
                role = getattr(msg, "role", None)
                content_val = getattr(msg, "content", None)
                if not isinstance(content_val, str) or not content_val.strip():
                    continue
                if role == "user":
                    container.mount(UserMessage(content_val))
                elif role in ("assistant", "system"):
                    rc = getattr(msg, "reasoning_content", None) or ""
                    container.mount(HistoryMessage(content_val, rc))

        self.run_worker(_render())
