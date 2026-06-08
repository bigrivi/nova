from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional

MAX_RENDERED_DIFF_LINES = 80


# ── Palette ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolRenderPalette:
    tool: str
    text: str
    muted: str
    dim: str
    warning: str
    success: str
    error: str
    info: str
    path: str
    string: str
    diff_title: str
    status_bg: str

    def accent(self, name: str = "muted") -> str:
        return getattr(self, name, self.muted)


# ── Registry ─────────────────────────────────────────────────────────────────

@dataclass
class ToolRenderer:
    cat: str
    icon: str
    accent_css: str
    label: str | None = None
    summary: Callable[[dict], str] = lambda _: ""
    params: Callable[[dict], list[tuple[str, str]]] | None = None
    render_detail: Callable[[dict, ToolRenderPalette], list[str]] | None = None
    on_result: Callable[[str, ToolRenderPalette], list[str]] | None = None
    on_done: Callable[..., None] | None = None
    show_detail: bool | Callable[[dict], bool] = True
    default_open: bool = False
    show_time: bool = False
    css_class: str | None = None


REGISTRY: dict[str, ToolRenderer] = {}


# ── Tool helper factories ───────────────────────────────────────────────────

def _param_lines(
    params: list[tuple[str, str]],
    palette: ToolRenderPalette,
    description: str = "",
) -> list[str]:
    lines: list[str] = []
    for key, value in params:
        if description and value in description:
            continue
        lines.append(f"\033[2m{palette.muted}{key}{_RS}  {palette.text}{value}{_RS}")
    return lines


async def mount_diff_into_block(block, original: str, modified: str, file_path: str = "") -> None:
    from textual_diff_view import DiffView

    body = block.query_one("#body")
    await body.remove_children()
    dv = DiffView(
        path_original="", path_modified=file_path,
        code_original=original,
        code_modified=modified,
        split=True, annotations=True,
    )
    body.update("")
    await body.mount(dv)
    body.display = True


async def _edit_on_done(block, raw_args: dict) -> None:
    await mount_diff_into_block(
        block,
        raw_args["oldString"],
        raw_args["newString"],
        raw_args.get("filePath", ""),
    )


# ── Render helpers ──────────────────────────────────────────────────────────

def _shell_on_result(content: str, palette: ToolRenderPalette) -> list[str]:
    has_error = "[stderr]" in content
    lines: list[str] = []
    if content:
        for line in content.rstrip("\n").split("\n"):
            lines.append(f"{palette.error if has_error else palette.text}{line}{_RS}")
    return lines


def _web_search_render_result(content: str, palette: ToolRenderPalette) -> list[str]:
    lines: list[str] = []
    for line in content.strip().split("\n"):
        lines.append(f"{palette.text}{line}{_RS}")
    return lines


def _web_fetch_render_result(content: str, palette: ToolRenderPalette) -> list[str]:
    text = content[:600] + ("\n…" if len(content) > 600 else "")
    return [f"{palette.text}{text}{_RS}"] if text else []


def _file_list_result(content: str, palette: ToolRenderPalette) -> list[str]:
    lines: list[str] = []
    for line in content.strip().split("\n"):
        if line.strip():
            lines.append(f"  {palette.success}✓ {_RS}{palette.text}{line}{_RS}")
    return lines


def _match_list_result(content: str, palette: ToolRenderPalette) -> list[str]:
    lines: list[str] = []
    for line in content.strip().split("\n"):
        if ":" in line and "/" in line:
            parts = line.split(":", 1)
            lines.append(f"{palette.path}{parts[0]}{_RS}:{palette.info}{parts[1]}{_RS}")
        elif line.strip():
            lines.append(f"{palette.text}{line}{_RS}")
    return lines


def _memory_list_result(content: str, palette: ToolRenderPalette) -> list[str]:
    lines: list[str] = []
    for line in content.strip().split("\n"):
        if ":" in line:
            parts = line.split(":", 1)
            lines.append(f"{palette.path}{parts[0]}{_RS}:{palette.text}{parts[1]}{_RS}")
        elif line.strip():
            lines.append(f"{palette.muted}{line}{_RS}")
    return lines


def _skill_list_result(content: str, palette: ToolRenderPalette) -> list[str]:
    lines: list[str] = []
    for line in content.strip().split("\n"):
        if line.strip():
            lines.append(f"{palette.success}◈ {_RS}{palette.text}{line}{_RS}")
    return lines


def _browser_state_detail(args: dict, palette: ToolRenderPalette) -> list[str]:
    return []


def _browser_state_result(content: str, palette: ToolRenderPalette) -> list[str]:
    lines: list[str] = []
    for line in content.strip().split("\n"):
        if line.strip():
            lines.append(f"{palette.text}{line}{_RS}")
    return lines


def _todo_write_render_detail(args: dict, palette: ToolRenderPalette) -> list[str]:
    todos = args.get("todos", [])
    if not isinstance(todos, list):
        return []
    lines: list[str] = []
    for t in todos:
        if not isinstance(t, dict):
            continue
        content = t.get("content", "")
        status = t.get("status", "pending")
        if status == "in_progress":
            lines.append(f"{palette.warning}[•]{_RS}  {palette.warning}{content}{_RS}")
        elif status == "completed":
            lines.append(f"{palette.muted}[✓]{_RS}  {palette.muted}{content}{_RS}")
        elif status == "cancelled":
            lines.append(f"{palette.muted}[ ]{_RS}  \033[9m{palette.muted}{content}{_RS}")
        else:
            lines.append(f"{palette.muted}[ ]{_RS}  {palette.muted}{content}{_RS}")
    return lines


def _delegate_to_agent_result(content: str, palette: ToolRenderPalette) -> list[str]:
    lines: list[str] = []
    lines.append(f"{palette.success}completed ✓{_RS}")
    if content.strip():
        lines.append(f"{palette.dim}{'─' * 40}{_RS}")
        for line in content.strip().split("\n"):
            lines.append(f"{palette.text}{line}{_RS}")
    return lines


def _install_skill_result(content: str, palette: ToolRenderPalette) -> list[str]:
    return [f"{palette.success}installed ✓{_RS}"]


# ── Browser use helpers ──────────────────────────────────────────────────────

_BROWSER_STATE_ACTIONS = frozenset({
    "get_state", "get_dropdown_options", "extract_content", "web_search",
})


def _browser_use_show_detail(args: dict) -> bool:
    return args.get("action", "") in _BROWSER_STATE_ACTIONS


def _browser_use_show_time(args: dict) -> bool:
    return args.get("action", "") not in _BROWSER_STATE_ACTIONS


def _browser_use_summary(args: dict) -> str:
    action = args.get("action", "")
    if action == "go_to_url":
        url = args.get("url", "") or ""
        return f"go_to_url {url}" if url else action
    if action == "click_element":
        return f"click_element [{args.get('index')}]"
    if action == "input_text":
        t = args.get("text", "")
        idx = args.get("index")
        return f"input_text [{idx}]: {t[:40]}" if t else f"input_text [{idx}]"
    if action == "web_search":
        q = args.get("query", "")
        return f'web_search: "{q[:40]}"' if q else action
    if action == "scroll_to_text":
        t = args.get("text", "")
        return f'scroll_to_text: "{t[:40]}"' if t else action
    if action == "scroll_down":
        amount = args.get("scroll_amount", "")
        return f"scroll_down [{amount}]" if amount else action
    if action == "scroll_up":
        amount = args.get("scroll_amount", "")
        return f"scroll_up [{amount}]" if amount else action
    if action == "extract_content":
        goal = args.get("goal", "")
        return f'extract: "{goal[:40]}"' if goal else action
    if action == "switch_tab":
        return f"switch_tab [{args.get('tab_id')}]"
    if action == "open_tab":
        url = args.get("url", "") or ""
        return f"open_tab {url}" if url else action
    if action == "send_keys":
        return f"send_keys: {args.get('keys', '')}"
    if action == "get_dropdown_options":
        return f"get_dropdown_options [{args.get('index')}]"
    if action == "select_dropdown_option":
        t = args.get("text", "")
        idx = args.get("index")
        return f"select_option [{idx}]: {t[:40]}" if t else f"select_option [{idx}]"
    if action == "go_back":
        return "go_back"
    if action == "wait":
        seconds = args.get("seconds", "")
        return f"wait [{seconds}s]" if seconds else action
    if action == "close_tab":
        return "close_tab"
    if action == "cleanup":
        return "cleanup"
    return action


# ── Register all tools ───────────────────────────────────────────────────────

def _register_tools() -> None:
    REGISTRY.update({

        # ── Code & File ──
        "shell": ToolRenderer(
            cat="Code & File", icon="⚡", accent_css="warning",
            summary=lambda a: (
                a.get("description", "")
                or (a.get("command", "") or "").split("\n")[0][:48]
            ),
            render_detail=lambda a, p: [a["command"]] if a.get("command") else [],
            on_result=_shell_on_result,
            show_detail=True, default_open=True, show_time=True,
        ),
        "code_run": ToolRenderer(
            cat="Code & File", icon="⚡", accent_css="warning",
            summary=lambda a: (
                a.get("description", "")
                or (a.get("code", "") or "").split("\n")[0][:48]
            ),
            render_detail=lambda a, p: [a.get("code", "")] if a.get("code") else [],
            on_result=_shell_on_result,
            show_detail=True, default_open=True, show_time=True,
        ),
        "read": ToolRenderer(
            cat="Code & File", icon="📄", accent_css="muted",
            summary=lambda a: f"{a.get('filePath', '')}  L{a.get('offset', 1)}–{a.get('offset', 1) + (a.get('limit', 50) or 50) - 1}",
            params=lambda a: [("filePath", a["filePath"])] if a.get("filePath") else [],
            show_detail=False,
        ),
        "edit": ToolRenderer(
            cat="Code & File", icon="📝", accent_css="tool",
            summary=lambda a: a.get("filePath", "") or "",
            show_detail=False,
            default_open=True,
            on_done=_edit_on_done,
        ),
        "write": ToolRenderer(
            cat="Code & File", icon="✏️", accent_css="info",
            summary=lambda a: a.get("filePath", "") or "",
            params=lambda a: [("filePath", a["filePath"])] if a.get("filePath") else [],
            show_detail=False,
        ),
        "write_files": ToolRenderer(
            cat="Code & File", icon="✏️", accent_css="info",
            summary=lambda a: f"{len(a.get('files', []))} files",
            params=lambda a: [("files", str(a.get("files", [])))] if a.get("files") else [],
            on_result=_file_list_result,
            show_detail=True, default_open=False,
        ),

        # ── Search ──
        "glob": ToolRenderer(
            cat="Search", icon="🔎", accent_css="info",
            summary=lambda a: f"{a.get('pattern', '')}  in {a.get('path', '.')}",
            params=lambda a: [("pattern", a.get("pattern", ""))] if a.get("pattern") else [],
            on_result=_match_list_result,
            show_detail=True, default_open=False,
        ),
        "grep": ToolRenderer(
            cat="Search", icon="🔎", accent_css="info",
            summary=lambda a: f"\"{a.get('pattern', '')}\"  in {a.get('include', '*')}",
            params=lambda a: (
                [("pattern", a["pattern"])] + ([("include", a["include"])] if a.get("include") else [])
            ) if a.get("pattern") else [],
            on_result=_match_list_result,
            show_detail=True, default_open=False,
        ),
        "web_search": ToolRenderer(
            cat="Search", icon="🔍", accent_css="success",
            summary=lambda a: f"\"{a.get('query', '')}\"",
            params=lambda a: [("query", a.get("query", ""))] if a.get("query") else [],
            on_result=_web_search_render_result,
            show_detail=True, default_open=False, show_time=True,
        ),
        "web_fetch": ToolRenderer(
            cat="Search", icon="🌐", accent_css="success",
            summary=lambda a: a.get("url", "") or "",
            params=lambda a: [("url", a.get("url", ""))] if a.get("url") else [],
            on_result=_web_fetch_render_result,
            show_detail=True, default_open=False, show_time=True,
        ),

        # ── Memory ──
        "save_memory": ToolRenderer(
            cat="Memory", icon="💾", accent_css="tool",
            summary=lambda a: f"{a.get('key', '')}  [{a.get('memory_type', 'fact')} · {a.get('scope', 'user')}]",
            params=lambda a: [("key", a["key"])] if a.get("key") else [],
            show_detail=False,
        ),
        "search_memory": ToolRenderer(
            cat="Memory", icon="🔮", accent_css="tool",
            summary=lambda a: f"\"{a.get('query', '')}\"",
            params=lambda a: [("query", a.get("query", ""))] if a.get("query") else [],
            on_result=_memory_list_result,
            show_detail=True, default_open=False,
        ),
        "delete_memory": ToolRenderer(
            cat="Memory", icon="🗑️", accent_css="error",
            summary=lambda a: a.get("id", "") or a.get("key", "") or "",
            params=lambda a: [("id", a.get("id", "") or a.get("key", ""))] if a.get("id") or a.get("key") else [],
            show_detail=False,
        ),
        "list_memories": ToolRenderer(
            cat="Memory", icon="📋", accent_css="tool",
            summary=lambda a: f"scope:{a.get('scope', 'all')}  limit:{a.get('limit', 20)}",
            params=lambda a: [("scope", a.get("scope", "")), ("limit", str(a.get("limit", 20)))] if a.get("scope") else [],
            on_result=_memory_list_result,
            show_detail=True, default_open=False,
        ),

        # ── Skills ──
        "list_skills": ToolRenderer(
            cat="Skills", icon="📦", accent_css="info",
            summary=lambda _: "installed skills",
            on_result=_skill_list_result,
            show_detail=True, default_open=False,
        ),
        "load_skill": ToolRenderer(
            cat="Skills", icon="📥", accent_css="info",
            summary=lambda a: a.get("skill_name", "") or "",
            params=lambda a: [("skill_name", a["skill_name"])] if a.get("skill_name") else [],
            show_detail=False,
        ),
        "install_skill": ToolRenderer(
            cat="Skills", icon="⬇️", accent_css="info",
            summary=lambda a: f"{a.get('skill_ref', '')}{' --force' if a.get('force') else ''}",
            params=lambda a: (
                [("skill_ref", a["skill_ref"])] + ([("force", str(a["force"]))] if a.get("force") is not None else [])
            ) if a.get("skill_ref") else [],
            on_result=_install_skill_result,
            show_detail=True, default_open=False, show_time=True,
        ),

        # ── Browser ──
        "browser_use": ToolRenderer(
            cat="Browser", icon="🌐", accent_css="info",
            summary=_browser_use_summary,
            render_detail=_browser_state_detail,
            on_result=_browser_state_result,
            show_detail=_browser_use_show_detail,
            show_time=_browser_use_show_time,
        ),

        # ── Other ──
        "read_image": ToolRenderer(
            cat="Other", icon="🖼️", accent_css="muted",
            summary=lambda a: a.get("file_path", "") or "",
            params=lambda a: [("file_path", a["file_path"])] if a.get("file_path") else [],
            show_detail=False,
        ),
        "todo_write": ToolRenderer(
            cat="Other", icon="✅", accent_css="warning",
            summary=lambda a: (
                (lambda ts: (
                    f"Working on: {next((t['content'] for t in ts if t.get('status') == 'in_progress'), '')[:60]}"
                    if any(t.get('status') == 'in_progress' for t in ts if isinstance(t, dict))
                    else (
                        f"Completed: {sum(1 for t in ts if isinstance(t, dict) and t.get('status') == 'completed')}/{len(ts)}"
                        if ts and isinstance(ts[0], dict) and all(not isinstance(t, dict) or t.get('status') in ('completed',) for t in ts)
                        else "Creating plan" if not any(isinstance(t, dict) and t.get('status') in ('completed', 'in_progress') for t in ts)
                        else "Updating plan"
                    )
                )))(a.get("todos", [])) if a.get("todos") else "",
            render_detail=_todo_write_render_detail,
            show_detail=True, default_open=False,
        ),
        "delegate_to_agent": ToolRenderer(
            cat="Other", icon="🤖", accent_css="tool",
            summary=lambda a: (
                f"\u2192 {a.get('agent_key', '')}: {(a.get('task', '') or '')[:60]}"
                if a.get("agent_key") else ""
            ),
            params=lambda a: (
                [("agent", a["agent_key"])]
                + ([("task", str(a["task"])[:60])] if a.get("task") else [])
                + ([("timeout", f"{a['timeout']}s")] if a.get("timeout") is not None else [])
            ) if a.get("agent_key") else [],
            on_result=_delegate_to_agent_result,
            show_detail=True, default_open=True, show_time=True,
        ),
        "install_python_package": ToolRenderer(
            cat="Other", icon="📦", accent_css="muted",
            summary=lambda a: f"{a.get('package', '')}=={a.get('version', '')}" if a.get("version") else a.get("package", ""),
            params=lambda a: (
                [("package", a["package"])] + ([("version", a["version"])] if a.get("version") else [])
            ) if a.get("package") else [],
            show_detail=False, show_time=True,
        ),
    })


_register_tools()


# ── ANSI constants ───────────────────────────────────────────────────────────

_RS = "\033[0m"
_BO = "\033[1m"
_DI = "\033[2m"

_C_TOOL = "\033[38;2;77;157;224m"
_C_TXT = "\033[38;2;205;214;224m"
_C_TXT2 = "\033[38;2;122;138;152m"
_C_TXT3 = "\033[38;2;70;83;94m"
_C_AMBER = "\033[38;2;212;168;67m"
_C_GREEN = "\033[38;2;61;170;106m"
_C_RED = "\033[38;2;204;79;79m"
_C_CYAN = "\033[38;2;61;168;184m"
_C_PURPLE = "\033[38;2;138;112;214m"
_C_STR = "\033[38;2;126;200;227m"

_BG_WAIT = "\033[48;2;26;32;48m"
_BG_RUN = "\033[48;2;30;22;8m"
_BG_OK = "\033[48;2;9;26;16m"
_BG_ERR = "\033[48;2;26;12;12m"

DEFAULT_TOOL_PALETTE = ToolRenderPalette(
    tool=_C_TOOL,
    text=_C_TXT,
    muted=_C_TXT2,
    dim=_C_TXT3,
    warning=_C_AMBER,
    success=_C_GREEN,
    error=_C_RED,
    info=_C_CYAN,
    path=_C_PURPLE,
    string=_C_STR,
    diff_title=_C_PURPLE,
    status_bg=_BG_WAIT,
)


def tool_palette_from_theme(colors) -> ToolRenderPalette:
    return ToolRenderPalette(
        tool=_fg_hex(colors.primary),
        text=_fg_hex(colors.foreground),
        muted=_fg_hex(colors.text_muted),
        dim=_fg_hex(colors.text_disabled),
        warning=_fg_hex(colors.warning),
        success=_fg_hex(colors.success),
        error=_fg_hex(colors.error),
        info=_fg_hex(colors.secondary),
        path=_fg_hex(colors.primary),
        string=_fg_hex(colors.secondary),
        diff_title=_fg_hex(colors.primary),
        status_bg=_bg_hex(colors.panel),
    )


_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


# ── Header rendering ─────────────────────────────────────────────────────────

def render_tool_block_header(
    state: str,
    tool_name: str,
    description: str,
    elapsed_ms: int | None,
    spinner_frame: int = 0,
    palette: ToolRenderPalette | None = None,
) -> tuple[str, str]:
    p = palette or DEFAULT_TOOL_PALETTE
    renderer = REGISTRY.get(tool_name)
    left_parts: list[str] = []
    right_parts: list[str] = []

    # Left: icon + label + description
    if renderer:
        accent = p.accent(renderer.accent_css)
        label = renderer.label or tool_name
        icon = renderer.icon
        icon_cp = icon[0]
        if unicodedata.east_asian_width(icon_cp) not in ('W', 'F'):
            icon += "\N{SPACE}"  # pad narrow icons to match wide-emoji column width
        left_parts.append(f"{icon} {accent}{_BO}{label}{_RS}")
    else:
        left_parts.append(f"  {p.tool}{_BO}{tool_name}{_RS}")

    if description:
        left_parts.append(f"  {p.muted}{description}{_RS}")

    # Right: state indicator + elapsed
    if state == "running":
        sp = _SPINNER_FRAMES[spinner_frame % len(_SPINNER_FRAMES)]
        right_parts.append(f"{p.warning}{sp} running{_RS}")
    elif state == "done":
        accent = p.accent(renderer.accent_css) if renderer else p.success
        right_parts.append(f"{accent}✓{_RS}")
        if elapsed_ms is not None and elapsed_ms >= 100:
            if elapsed_ms < 1000:
                right_parts.append(f"  {p.dim}{elapsed_ms}ms{_RS}")
            else:
                right_parts.append(f"  {p.dim}{elapsed_ms / 1000:.1f}s{_RS}")
    elif state == "error":
        right_parts.append(f"{p.error}✗{_RS}")

    return "".join(left_parts), "".join(right_parts)


# ── Diff rendering ───────────────────────────────────────────────────────────

def render_diff_block(
    text: str,
    max_rendered_diff_lines: int = MAX_RENDERED_DIFF_LINES,
    palette: ToolRenderPalette | None = None,
) -> str:
    p = palette or DEFAULT_TOOL_PALETTE
    rendered: list[str] = []
    lines = text.split("\n")
    if len(lines) > max_rendered_diff_lines:
        lines = lines[:max_rendered_diff_lines]
        lines.append(f"\033[2m{p.dim}... ({len(lines)} more lines truncated){_RS}")

    for line in lines:
        if line.startswith("---") or line.startswith("+++"):
            rendered.append(f"{_BO}{p.info}{line}{_RS}")
        elif line.startswith("@@"):
            rendered.append(f"{_BO}{p.warning}{line}{_RS}")
        elif line.startswith("+"):
            rendered.append(f"{p.success}{line}{_RS}")
        elif line.startswith("-"):
            rendered.append(f"{p.error}{line}{_RS}")
        else:
            rendered.append(f"{line}")
    return "\n".join(rendered)


# ── Tool utilities ───────────────────────────────────────────────────────────

def render_bash_command(command: str, palette: ToolRenderPalette | None = None) -> str:
    if not command:
        return ""
    p = palette or DEFAULT_TOOL_PALETTE
    tokens = command.split()
    result: list[str] = []
    for i, tok in enumerate(tokens):
        if i == 0:
            result.append(f"{p.info}{tok}{_RS}")
        elif tok.startswith(("--", "-")) and len(tok) > 1:
            result.append(f"{p.warning}{tok}{_RS}")
        elif tok.startswith(("~", "/", "./", "../")):
            result.append(f"{p.path}{tok}{_RS}")
        elif tok.startswith(("'", '"')):
            result.append(f"{p.string}{tok}{_RS}")
        else:
            result.append(f"{p.text}{tok}{_RS}")
    return " ".join(result)


def parse_tool_arguments(arguments: object) -> dict:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def truncate_preview(text: str, limit: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


# ── ANSI color utilities ─────────────────────────────────────────────────────

def _fgr(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


def _bgr(r: int, g: int, b: int) -> str:
    return f"\033[48;2;{r};{g};{b}m"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"Expected 6-digit hex color, got {value!r}")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _fg_hex(value: str) -> str:
    return _fgr(*_hex_to_rgb(value))


def _bg_hex(value: str) -> str:
    return _bgr(*_hex_to_rgb(value))
