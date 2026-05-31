from __future__ import annotations

import time

from rich.text import Text as RichText
from textual.containers import Horizontal
from textual.widgets import Static
from textual.widget import Widget

from nova.cli.tool_rendering import (
    _C_RED,
    _RS,
    render_tool_block_header,
)




class ToolBlock(Widget):

    _diff_tools = frozenset({"edit", "write", "write_files"})

    @property
    def _is_diff_tool(self) -> bool:
        return self._tool_name in self._diff_tools

    DEFAULT_CSS = """
    ToolBlock {
        margin: 0;
        height: auto;
        padding: 0 2;
        margin:0 0 1 0;
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
    """

    def __init__(
        self,
        tool_name: str,
        description: str = "",
        params: list[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._description = description
        self._params = params or []
        self._state = "pending"
        self._expanded = False
        self._started_at: float | None = None
        self._elapsed_ms: int | None = None
        self._body_content: str | None = None
        self._body_is_error = False
        self._spinner_frame = 0
        self._timer_handle = None
        self._left_ref: Static | None = None
        self._right_ref: Static | None = None
        self._body_ref: Static | None = None

    def compose(self):
        with Horizontal():
            yield Static(id="hd-left")
            yield Static(id="hd-right")
        yield Static(id="body")

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def set_running(self) -> None:
        self._state = "running"
        self._started_at = time.monotonic()
        self._expanded = True
        self._timer_handle = self.set_interval(0.12, self._tick)
        self._refresh()

    def set_done(self, body_ansi: str | None = None) -> None:
        self._state = "done"
        self._elapsed_ms = self._calc_elapsed()
        self._body_content = body_ansi or self._body_content
        self._body_is_error = False
        self._expanded = self._is_diff_tool
        self._stop_timer()
        self._refresh()

    def set_error(self, error_ansi: str | None = None) -> None:
        self._state = "error"
        self._elapsed_ms = self._calc_elapsed()
        self._body_content = error_ansi or self._body_content
        self._body_is_error = True
        self._expanded = True
        self._stop_timer()
        self._refresh()

    # ----------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------

    def on_mount(self) -> None:
        self._left_ref = self.query_one("#hd-left")
        self._right_ref = self.query_one("#hd-right")
        self._body_ref = self.query_one("#body")
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

    def _refresh(self) -> None:
        if self._left_ref is None:
            return
        elapsed = self._calc_elapsed() if self._state == "running" else self._elapsed_ms
        left, right = render_tool_block_header(
            self._state,
            self._tool_name,
            self._description,
            elapsed,
            self._spinner_frame,
        )
        self._left_ref.update(RichText.from_ansi(left))
        self._right_ref.update(RichText.from_ansi(right))

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
        if not self._body_content:
            return ""
        parts: list[str] = []
        if self._body_is_error:
            for line in self._body_content.splitlines():
                parts.append(f"{_C_RED}{line}{_RS}")
        else:
            for line in self._body_content.splitlines():
                parts.append(f"{line}")
        return "\n".join(parts)
