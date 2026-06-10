#!/usr/bin/env python3
"""
Demo script to preview tool call rendering in the TUI.

Shows every registered tool (except ask_user) as a ToolBlock
in its done state, with parameters visible in the body.

Keys: q quit

Run: python -m nova.cli.demo.demo_tool_call

To use a different theme:
    TEXTUAL_THEME=nord python -m nova.cli.demo.demo_tool_call
    TEXTUAL_THEME=catppuccin-mocha python -m nova.cli.demo.demo_tool_call
"""
from __future__ import annotations

import argparse

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Static

from nova.cli.tool_rendering import DEFAULT_TOOL_PALETTE, REGISTRY, _RS
from nova.cli.widgets.tool_block import ToolBlock


CATEGORIES: list[tuple[str, list[dict]]] = [
    ("Code & File", [
        dict(tool_name="shell", arguments=dict(command="ls -la", description="List files in current directory"),
             result="total 42\n-rw-r--r--    1 user  staff   123 Jan  1 00:00 main.py"),
        dict(tool_name="shell", arguments=dict(command="cat nonexistent.txt", description="Attempt to read a non-existent file"),
             result="cat: nonexistent.txt: No such file or directory", error=True),
        dict(tool_name="code_run", arguments=dict(code="print('hello')",
             description="Print a greeting"), result="hello"),
        dict(tool_name="code_run", arguments=dict(code="1/0", description="Trigger a division-by-zero error"),
             result="Traceback (most recent call last):\n  File \"<string>\", line 1, in <module>\nZeroDivisionError: division by zero", error=True),
        dict(tool_name="read", arguments=dict(
            filePath="src/main.py", offset=1, limit=50)),
        dict(tool_name="edit", arguments=dict(
            filePath="src/main.py",
            oldString="\"\"\"Application entry point.\"\"\"\n\nimport sys\nfrom pathlib import Path\n\n\ndef main():\n    args = sys.argv[1:]\n    if not args:\n        print(\"No arguments provided\")\n        return 1\n    for arg in args:\n        print(f\"Processing: {arg}\")\n    return 0\n\n\nif __name__ == \"__main__\":\n    exit(main())",
            newString="\"\"\"Application entry point with logging.\"\"\"\n\nimport sys\nimport logging\nfrom pathlib import Path\n\nlogger = logging.getLogger(__name__)\n\n\ndef main():\n    logging.basicConfig(level=logging.INFO)\n    args = sys.argv[1:]\n    if not args:\n        logger.warning(\"No arguments provided\")\n        print(\"Usage: python main.py <args>\")\n        return 1\n    for arg in args:\n        logger.info(\"Processing %s\", arg)\n        print(f\"Processing: {arg}\")\n    logger.info(\"Done\")\n    return 0\n\n\nif __name__ == \"__main__\":\n    exit(main())",
        )),
        dict(tool_name="write", arguments=dict(
            filePath="src/new.py", content="print('hi')\n")),
        dict(tool_name="write_files", arguments=dict(
            files=["a.py", "b.py"]), result="Created a.py\nCreated b.py"),
    ]),
    ("Search", [
        dict(tool_name="glob", arguments=dict(pattern="*.py",
             path="src/"), result="src/main.py\nsrc/core.py"),
        dict(tool_name="grep", arguments=dict(pattern="def main",
             include="*.py"), result="src/main.py:4:def main():"),
        dict(tool_name="web_search", arguments=dict(query="python async tutorial", description="Search for async python tutorials"),
             result="Title: asyncio — Asynchronous I/O — Python 3.14.5 documentation\nURL: https://docs.python.org/3/library/asyncio.html\n---\nTitle: Python Async Programming: The Complete Guide\nURL: https://datacamp.com/tutorial/python-async-programming"),
        dict(tool_name="web_fetch", arguments=dict(
            url="https://example.com"), result="# Page Title\n\nContent here..."),
    ]),
    ("Memory", [
        dict(tool_name="save_memory", arguments=dict(key="user_name", content="Alice",
             summary="user name: Alice", scope="user", memory_type="fact")),
        dict(tool_name="search_memory", arguments=dict(query="user preferences", scope="all",
             limit=5), result="mem_001: user name: Alice\nmem_002: prefers dark mode"),
        dict(tool_name="delete_memory", arguments=dict(id="mem_123")),
        dict(tool_name="list_memories", arguments=dict(scope="all", limit=20),
             result="mem_001: user name: Alice\nmem_002: prefers dark mode"),
    ]),
    ("Skills", [
        dict(tool_name="list_skills", arguments={},
             result="code-review\nrefactor\n"),
        dict(tool_name="load_skill", arguments=dict(skill_name="code-review")),
        dict(tool_name="install_skill", arguments=dict(
            skill_ref="team/review-skill", force=True), result="installed"),
    ]),
    ("Browser", [
        dict(tool_name="browser_use", arguments=dict(
            action="go_to_url", url="https://docs.python.org")),
        dict(tool_name="browser_use", arguments=dict(
            action="click_element", index=3)),
        dict(tool_name="browser_use", arguments=dict(
            action="input_text", index=2, text="async await")),
        dict(tool_name="browser_use", arguments=dict(
            action="web_search", query="python async tutorial")),
        dict(tool_name="browser_use", arguments=dict(
            action="scroll_to_text", text="see also")),
        dict(tool_name="browser_use", arguments=dict(
            action="scroll_down", scroll_amount=300)),
        dict(tool_name="browser_use", arguments=dict(action="scroll_up")),
        dict(tool_name="browser_use", arguments=dict(action="go_back")),
        dict(tool_name="browser_use", arguments=dict(action="wait", seconds=2)),
        dict(tool_name="browser_use", arguments=dict(
            action="extract_content", goal="get the main content")),
        dict(tool_name="browser_use", arguments=dict(
            action="switch_tab", tab_id=1)),
        dict(tool_name="browser_use", arguments=dict(
            action="open_tab", url="https://pypi.org")),
        dict(tool_name="browser_use", arguments=dict(action="close_tab")),
        dict(tool_name="browser_use", arguments=dict(
            action="send_keys", keys="Ctrl+F")),
        dict(tool_name="browser_use", arguments=dict(
            action="get_dropdown_options", index=0)),
        dict(tool_name="browser_use", arguments=dict(
            action="select_dropdown_option", index=0, text="Sort by date")),
        dict(tool_name="browser_use", arguments=dict(action="get_state"),
             result="https://docs.python.org/3/\n[0] link: Python 3.12 Documentation\n[1] button: Search"),
        dict(tool_name="browser_use", arguments=dict(action="cleanup")),
    ]),
    ("Other", [
        dict(tool_name="read_image", arguments=dict(
            file_path="/path/to/screenshot.png")),
        dict(tool_name="todo_write", arguments=dict(todos=[
            {"content": "Fix login bug", "status": "in_progress", "priority": "high"},
            {"content": "Write unit tests", "status": "pending", "priority": "medium"},
            {"content": "Document API", "status": "completed", "priority": "low"},
        ])),
        dict(tool_name="delegate_to_agent", arguments=dict(agent_key="code-review",
             task="Review the PR", timeout=300), result="Code review complete. Found 2 issues."),
        dict(tool_name="install_python_package",
             arguments=dict(package="httpx", version="0.28.0")),
    ]),
]


class DemoApp(App):
    CSS = """
    Screen {
        background: $background;
    }
    #header {
        dock: top;
        height: 3;
        background: $panel;
        padding: 1 2;
        color: $foreground;
    }
    ScrollableContainer {
        padding: 0 1;
    }
    .category-label {
        background: $surface;
        color: $text-primary;
        padding: 1 2;
        margin: 1 0 0 0;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self, theme: str = "textual-dark") -> None:
        super().__init__()
        self.theme = theme
        self._all_entries = [t for _, tools in CATEGORIES for t in tools]
        self._entry_index = 0

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Demo: Tool call rendering  [red]q[/] to quit",
            id="header",
        )
        with ScrollableContainer():
            for category, tools in CATEGORIES:
                yield Static(f"[bold]{category}[/]", classes="category-label")
                for tool in tools:
                    name = tool["tool_name"]
                    args = tool["arguments"]
                    renderer = REGISTRY.get(name)
                    desc = renderer.summary(args) if renderer else name
                    detail: list[str] | None = None
                    if renderer:
                        if renderer.render_detail:
                            detail = renderer.render_detail(
                                args, DEFAULT_TOOL_PALETTE)
                        elif renderer.params:
                            p = DEFAULT_TOOL_PALETTE
                            detail = [f"\033[2m{p.muted}{k}{_RS}  {p.text}{v}{_RS}" for k, v in (
                                renderer.params(args) or []) if not (desc and v in desc)]
                    block = ToolBlock(
                        tool_name=name,
                        summary=desc,
                        detail_lines=detail,
                        show_right=True,
                        raw_args=args,
                    )
                    yield block

    def on_mount(self) -> None:
        blocks = list(self.query(ToolBlock))
        for block in blocks:
            block.set_running()
        self.set_timer(0.3, self._finish_all)

    def _finish_all(self) -> None:
        from nova.cli.tool_rendering import tool_palette_from_theme
        from nova.cli.theme_colors import get_theme_colors

        palette = tool_palette_from_theme(get_theme_colors(self))
        for block in self.query(ToolBlock):
            td = self._next_entry(block._tool_name)
            if td and td.get("error"):
                block.set_error(td.get("result", ""))
            else:
                renderer = REGISTRY.get(block._tool_name)
                result_lines = None
                if td and renderer and renderer.on_result and td.get("result"):
                    result_lines = renderer.on_result(td["result"], palette)
                block.set_done(result_lines)

    def _next_entry(self, name: str) -> dict | None:
        while self._entry_index < len(self._all_entries):
            entry = self._all_entries[self._entry_index]
            self._entry_index += 1
            if entry["tool_name"] == name:
                return entry
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Demo tool call rendering with Textual themes"
    )
    parser.add_argument(
        "--theme",
        default="textual-dark",
        help="Textual theme to use (default: textual-dark)",
    )
    args = parser.parse_args()
    DemoApp(theme=args.theme).run()
