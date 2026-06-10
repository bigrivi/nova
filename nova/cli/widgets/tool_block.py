from __future__ import annotations

import asyncio
import time

from rich.text import Text as RichText
from textual.containers import Horizontal
from textual.widgets import Static
from textual.widget import Widget

from nova.cli.tool_rendering import (
    _RS,
    DEFAULT_TOOL_PALETTE,
    REGISTRY,
    ToolRenderPalette,
    render_tool_block_header,
)

MAX_BODY_LINES = 15


class _ClickableBody(Static):
    def on_click(self) -> None:
        parent = self.parent
        if parent and isinstance(parent, ToolBlock):
            parent._on_body_click()


class ToolBlock(Widget):

    DEFAULT_CSS = """
    ToolBlock {
        height: auto;
        padding: 1 1;
        margin: 0 0 1 0;
        background: $surface;
    }
    ToolBlock > Horizontal {
        height: auto;
        width: auto;
        margin: 0;
        padding: 0;
    }
    #hd-left {
        width: 1fr;
        height: auto;
        padding: 0 1 0 0;
    }
    #hd-right {
        width: auto;
        height: auto;
        padding: 0 1 0 0;
        text-align: right;
    }
    #body {
        height: auto;
        display: none;
        padding: 0 1 0 3;
    }
    #body.visible {
        display: block;
    }
    #body DiffView .title {
        display: none;
    }
    """

    def __init__(
        self,
        tool_name: str,
        summary: str = "",
        detail_lines: list[str] | None = None,
        palette: ToolRenderPalette | None = None,
        show_right: bool = True,
        css_class: str | None = None,
        raw_args: dict | None = None,
    ) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._summary = summary
        self._detail_lines = detail_lines or []
        self._raw_args = raw_args or {}
        self._stored_palette = palette
        self._show_right = show_right
        self._state = "pending"
        self._expanded = False
        self._started_at: float | None = None
        self._elapsed_ms: int | None = None
        self._result_lines: list[str] | None = None
        self._body_is_error = False
        self._spinner_frame = 0
        self._timer_handle = None
        self._left_ref: Static | None = None
        self._right_ref: Static | None = None
        self._body_ref: Static | None = None
        self._css_class = css_class
        self._renderer = REGISTRY.get(tool_name)
        self._pending_diff = False
        self._diff_mounted = False
        self._body_expanded = False

    def compose(self):
        with Horizontal():
            yield Static(id="hd-left")
            yield Static(id="hd-right")
        yield _ClickableBody(id="body")

    def _on_body_click(self) -> None:
        if self._body_ref and self._body_ref.display:
            self._body_expanded = not self._body_expanded
            self._refresh()

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def set_running(self) -> None:
        self._state = "running"
        self._started_at = time.monotonic()
        self._expanded = True
        self._timer_handle = self.set_interval(0.12, self._tick)
        self._refresh()

    def _should_show_detail(self) -> bool:
        if not self._renderer:
            return True
        if callable(self._renderer.show_detail):
            return self._renderer.show_detail(self._raw_args)
        return self._renderer.show_detail

    def set_done(self, result_lines: list[str] | None = None) -> None:
        self._state = "done"
        self._elapsed_ms = self._calc_elapsed()
        self._result_lines = result_lines
        self._body_is_error = False
        self._body_expanded = False
        self._expanded = (
            self._should_show_detail()
            and (
                (self._renderer and self._renderer.default_open)
                or bool(self._detail_lines)
                or bool(self._result_lines)
            )
        )
        self._stop_timer()
        if self._renderer and self._renderer.on_done and not self._diff_mounted:
            if self.is_mounted:
                asyncio.create_task(self._run_on_done())
            else:
                self._pending_diff = True
        self._refresh()

    async def _run_on_done(self) -> None:
        await self._renderer.on_done(self, self._raw_args)
        self._diff_mounted = True

    def set_error(self, message: str = "") -> None:
        self._state = "error"
        self._elapsed_ms = self._calc_elapsed()
        if message:
            self._result_lines = [message]
            self._body_is_error = True
        self._expanded = True
        self._stop_timer()
        self._refresh()


    # ----------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------

    async def on_mount(self) -> None:
        self._left_ref = self.query_one("#hd-left")
        self._right_ref = self.query_one("#hd-right")
        self._body_ref = self.query_one("#body")
        if self._css_class:
            self.add_class(self._css_class)
        if self._pending_diff:
            self._pending_diff = False
            await self._run_on_done()
        self._refresh()

    # ----------------------------------------------------------------
    # Internal
    # ----------------------------------------------------------------

    def _tick(self) -> None:
        if self._state == "running":
            self._spinner_frame += 1
            self._refresh()

    def _stop_timer(self) -> None:
        if self._timer_handle is not None:
            self._timer_handle.stop()
            self._timer_handle = None

    def _calc_elapsed(self) -> int:
        if self._started_at is not None:
            return int((time.monotonic() - self._started_at) * 1000)
        return 0

    def _palette(self) -> ToolRenderPalette:
        return self._stored_palette or DEFAULT_TOOL_PALETTE

    def _show_time_enabled(self) -> bool:
        if not self._renderer:
            return False
        if callable(self._renderer.show_time):
            return self._renderer.show_time(self._raw_args)
        return self._renderer.show_time

    def _refresh(self) -> None:
        if self._left_ref is None:
            return
        p = self._palette()
        if self._show_time_enabled():
            elapsed = self._calc_elapsed() if self._state == "running" else self._elapsed_ms
        else:
            elapsed = None
        left, right = render_tool_block_header(
            self._state,
            self._tool_name,
            self._summary,
            elapsed,
            self._spinner_frame,
            palette=p,
        )
        self._left_ref.update(RichText.from_ansi(left))
        if self._show_right:
            self._right_ref.update(RichText.from_ansi(right))
            self._right_ref.display = True
        else:
            self._right_ref.display = False

        if self._expanded:
            body = self._build_body()
            if body:
                self._body_ref.update(RichText.from_ansi(body))
                self._body_ref.display = True
            else:
                self._body_ref.display = False
        else:
            self._body_ref.display = False

    def _build_body(self) -> str:
        p = self._palette()
        lines: list[str] = []

        if self._detail_lines:
            for l in self._detail_lines:
                lines.extend(l.split("\n"))

        if self._result_lines:
            if lines:
                lines.append(f"{p.dim}{'─' * 40}{_RS}")
            if self._body_is_error:
                for line in self._result_lines:
                    lines.extend(line.split("\n"))
                    lines[-1] = f"{p.error}{lines[-1]}{_RS}"
            else:
                for line in self._result_lines:
                    lines.extend(line.split("\n"))

        if not self._body_expanded and len(lines) > MAX_BODY_LINES:
            hidden = len(lines) - MAX_BODY_LINES
            lines = lines[:MAX_BODY_LINES]
            lines.append(f"{p.dim}... ({hidden} more lines, click to expand){_RS}")

        return "\n".join(lines)
