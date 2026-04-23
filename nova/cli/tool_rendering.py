from __future__ import annotations

import json
from typing import Optional


MAX_RENDERED_DIFF_LINES = 80


def render_tool_call(tool_call: object) -> str:
    name = tool_call.name if hasattr(tool_call, "name") else str(tool_call)
    arguments = tool_call.arguments if hasattr(tool_call, "arguments") else ""
    bullet = "\033[32m•\033[0m"
    action_text = render_tool_action(name, arguments)
    title = f"\033[1;37m{action_text}\033[0m"
    raw_args = str(arguments or "").strip()
    if not raw_args or action_text != (name if isinstance(name, str) else str(name)):
        return f"{bullet} {title}"

    compact_args = raw_args
    try:
        compact_args = json.dumps(
            json.loads(compact_args),
            ensure_ascii=False,
            separators=(", ", ": "),
        )
    except (TypeError, ValueError):
        pass
    compact_args = " ".join(compact_args.split())
    if len(compact_args) > 140:
        compact_args = compact_args[:137] + "..."
    args_line = f"\033[2;37m{compact_args}\033[0m"
    return f"{bullet} {title}\n  {args_line}"


def render_tool_result(tool_name: object, content: object) -> Optional[str]:
    if not isinstance(tool_name, str) or not isinstance(content, str):
        return None

    normalized_name = tool_name.strip().lower()
    stripped = content.strip()
    if not stripped:
        return None

    if normalized_name in {"edit", "write"} and "\n--- " in content and "\n+++ " in content and "\n@@ " in content:
        headline, _, diff_body = stripped.partition("\n\n")
        rendered_diff = render_diff_block(diff_body or headline)
        label = normalized_name.upper()
        title = f"\033[1;35m[{label} DIFF]\033[0m {headline}"
        return f"{title}\n{rendered_diff}"

    preview = render_tool_result_preview(normalized_name, stripped)
    return preview


def render_tool_action(name: object, arguments: object) -> str:
    if not isinstance(name, str):
        return str(name)

    args = parse_tool_arguments(arguments)
    normalized_name = name.strip().lower()

    if normalized_name == "bash":
        command = args.get("command")
        if isinstance(command, str) and command.strip():
            return f"Ran {truncate_preview(command.strip(), limit=80)}"
    if normalized_name == "read":
        file_path = args.get("filePath")
        if isinstance(file_path, str) and file_path.strip():
            return f"Read {file_path.strip()}"
    if normalized_name == "glob":
        pattern = args.get("pattern")
        if isinstance(pattern, str) and pattern.strip():
            return f"Matched files with {truncate_preview(pattern.strip(), limit=60)}"
    if normalized_name == "grep":
        pattern = args.get("pattern")
        if isinstance(pattern, str) and pattern.strip():
            return f"Searched code for {truncate_preview(pattern.strip(), limit=60)}"
    if normalized_name == "web_search":
        query = args.get("query")
        if isinstance(query, str) and query.strip():
            return f'Searched web for "{truncate_preview(query.strip(), limit=60)}"'
    if normalized_name == "web_fetch":
        url = args.get("url")
        if isinstance(url, str) and url.strip():
            return f"Fetched {url.strip()}"
    if normalized_name == "search_memory":
        query = args.get("query")
        if isinstance(query, str) and query.strip():
            return f'Searched memory for "{truncate_preview(query.strip(), limit=60)}"'
    if normalized_name == "save_memory":
        key = args.get("key")
        if isinstance(key, str) and key.strip():
            return f"Saved memory {truncate_preview(key.strip(), limit=60)}"
    if normalized_name == "delete_memory":
        memory_id = args.get("id")
        key = args.get("key")
        if isinstance(memory_id, str) and memory_id.strip():
            return f"Deleted memory {memory_id.strip()}"
        if isinstance(key, str) and key.strip():
            return f"Deleted memory {truncate_preview(key.strip(), limit=60)}"
    if normalized_name == "list_memories":
        return "Listed memories"

    return name


def render_diff_block(text: str, max_rendered_diff_lines: int = MAX_RENDERED_DIFF_LINES) -> str:
    lines = text.splitlines()
    if len(lines) > max_rendered_diff_lines:
        hidden = len(lines) - max_rendered_diff_lines
        lines = lines[:max_rendered_diff_lines]
        lines.append(f"... ({hidden} more diff lines not shown)")

    rendered: list[str] = []
    for line in lines:
        if line.startswith(("--- ", "+++ ")):
            rendered.append(f"\033[1;36m{line}\033[0m")
        elif line.startswith("@@"):
            rendered.append(f"\033[1;33m{line}\033[0m")
        elif line.startswith("+") and not line.startswith("+++ "):
            rendered.append(f"\033[32m{line}\033[0m")
        elif line.startswith("-") and not line.startswith("--- "):
            rendered.append(f"\033[31m{line}\033[0m")
        else:
            rendered.append(line)
    return "\n".join(rendered)


def render_tool_result_preview(tool_name: str, content: str) -> str:
    preview_lines = build_tool_preview_lines(tool_name, content)
    if preview_lines is None:
        return content

    rendered: list[str] = []
    for index, line in enumerate(preview_lines):
        rendered.append(style_tool_preview_line(line, is_first=index == 0))
    return "\n".join(rendered)


def style_tool_preview_line(line: str, is_first: bool) -> str:
    prefix = "└" if is_first else "│"
    return f"  \033[2;37m{prefix} {line}\033[0m"


def build_tool_preview_lines(tool_name: str, content: str) -> Optional[list[str]]:
    lines = content.splitlines()
    if not lines:
        return [content]

    if tool_name == "bash":
        return preview_bash_result(lines)
    if tool_name == "glob":
        return preview_counted_list(lines, fallback_title="Matched files", item_limit=3)
    if tool_name == "grep":
        return preview_counted_list(lines, fallback_title="Search matches", item_limit=3)
    if tool_name == "read":
        return preview_read_result(lines)
    if tool_name == "web_search":
        return preview_web_search_result(lines)
    if tool_name == "web_fetch":
        return preview_web_fetch_result(lines)
    if tool_name == "search_memory":
        return preview_search_memory_result(lines)
    if tool_name == "list_memories":
        return preview_list_memories_result(lines)
    if tool_name == "save_memory":
        return preview_save_memory_result(lines)
    if tool_name == "delete_memory":
        return preview_delete_memory_result(lines)
    return None


def parse_tool_arguments(arguments: object) -> dict:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        return {}
    text = arguments.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def truncate_preview(text: str, limit: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def preview_bash_result(lines: list[str]) -> list[str]:
    if lines and lines[0].strip() == "(no output)":
        return ["(no output)"]
    return preview_generic_lines(lines, max_lines=4)


def preview_read_result(lines: list[str]) -> list[str]:
    visible_lines = [line for line in lines if line.strip()]
    if not visible_lines:
        return ["(empty file)"]

    preview_lines = visible_lines[:3]
    if len(visible_lines) > 3:
        preview_lines.append(f"... ({len(visible_lines) - 3} more lines)")
    first_line = preview_lines[0]
    return [f"Read {len(visible_lines)} lines", first_line, *preview_lines[1:]]


def preview_counted_list(lines: list[str], fallback_title: str, item_limit: int) -> list[str]:
    header = lines[0].strip() if lines else fallback_title
    items = [line for line in lines[1:] if line.strip()]
    preview = [header]
    preview.extend(items[:item_limit])
    if len(items) > item_limit:
        preview.append(f"... ({len(items) - item_limit} more)")
    return preview


def preview_generic_lines(lines: list[str], max_lines: int) -> list[str]:
    preview_lines = lines[:max_lines]
    if len(lines) > max_lines:
        preview_lines.append(f"... ({len(lines) - max_lines} more lines)")
    return preview_lines


def preview_web_search_result(lines: list[str]) -> list[str]:
    non_empty = [line.strip() for line in lines if line.strip()]
    if not non_empty:
        return ["No search results"]

    title = non_empty[0]
    url = ""
    remainder_start = 1
    if len(non_empty) > 1 and non_empty[1].startswith(("http://", "https://")):
        url = non_empty[1]
        remainder_start = 2

    body_lines = non_empty[remainder_start:remainder_start + 2]
    preview = [title]
    if url:
        preview.append(url)
    preview.extend(body_lines)
    hidden = len(non_empty) - len(preview)
    if hidden > 0:
        preview.append(f"... ({hidden} more lines)")
    return preview


def preview_web_fetch_result(lines: list[str]) -> list[str]:
    non_empty = [line.strip() for line in lines if line.strip()]
    if not non_empty:
        return ["Fetched content is empty"]

    first = non_empty[0]
    if first.startswith("#"):
        title = first
        body_lines = non_empty[1:3]
        preview = [title, *body_lines]
        hidden = len(non_empty) - len(preview)
        if hidden > 0:
            preview.append(f"... ({hidden} more lines)")
        return preview

    body_preview = truncate_preview(" ".join(non_empty[:3]), limit=160)
    preview = [body_preview]
    if len(non_empty) > 3:
        preview.append(f"... ({len(non_empty) - 3} more lines)")
    return preview


def preview_search_memory_result(lines: list[str]) -> list[str]:
    if not lines:
        return ["No memories found"]
    header = lines[0].strip()
    items = extract_memory_summaries(lines[1:], item_limit=3)
    if not items:
        return [header]
    return [header, *items]


def preview_list_memories_result(lines: list[str]) -> list[str]:
    if not lines:
        return ["No memories stored."]
    header = lines[0].strip()
    items = extract_memory_summaries(lines[1:], item_limit=4)
    if not items:
        return [header]
    return [header, *items]


def preview_save_memory_result(lines: list[str]) -> list[str]:
    if not lines:
        return ["Memory saved."]
    preview = [lines[0].strip()]
    summary = extract_first_prefixed_value(lines[1:], "  summary:")
    scope = extract_first_prefixed_value(lines[1:], "  scope:")
    memory_type = extract_first_prefixed_value(lines[1:], "  type:")
    key = extract_first_prefixed_value(lines[1:], "  key:")
    if summary:
        preview.append(f"summary: {summary}")
    elif key:
        preview.append(f"key: {key}")
    meta_parts = []
    if scope:
        meta_parts.append(scope)
    if memory_type:
        meta_parts.append(memory_type)
    if meta_parts:
        preview.append(f"meta: {' / '.join(meta_parts)}")
    return preview


def preview_delete_memory_result(lines: list[str]) -> list[str]:
    return [lines[0].strip()] if lines else ["No memory deleted."]


def extract_memory_summaries(lines: list[str], item_limit: int) -> list[str]:
    items: list[str] = []
    current_summary: Optional[str] = None
    current_meta: dict[str, str] = {}

    def flush() -> None:
        nonlocal current_summary, current_meta
        if current_summary:
            meta_parts = []
            scope = current_meta.get("scope")
            memory_type = current_meta.get("type")
            if scope:
                meta_parts.append(scope)
            if memory_type:
                meta_parts.append(memory_type)
            if meta_parts:
                items.append(f"{current_summary} [{' / '.join(meta_parts)}]")
            else:
                items.append(current_summary)
        current_summary = None
        current_meta = {}

    for raw_line in lines:
        line = raw_line.rstrip()
        if line.startswith("- id:"):
            flush()
            continue
        if line.startswith("  scope:"):
            current_meta["scope"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("  type:"):
            current_meta["type"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("  summary:"):
            current_summary = line.split(":", 1)[1].strip()
            continue
    flush()

    preview = items[:item_limit]
    if len(items) > item_limit:
        preview.append(f"... ({len(items) - item_limit} more memories)")
    return preview


def extract_first_prefixed_value(lines: list[str], prefix: str) -> Optional[str]:
    for line in lines:
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None
