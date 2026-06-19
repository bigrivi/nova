import asyncio

from opentui.components.code_renderable import CodeRenderable
from opentui.components._syntax_highlight import (
    TreeSitterClient,
    SyntaxStyle,
)


def sync_code_block(
    content: str,
    filetype: str,
    syntax_style: object,
    tree_sitter_client: TreeSitterClient,
) -> CodeRenderable:
    content = content.lstrip("\n\r")
    cr = CodeRenderable(
        content=content,
        filetype=filetype,
        syntax_style=syntax_style,
        tree_sitter_client=tree_sitter_client,
        wrap_mode="none",
    )

    if filetype:
        _apply_highlight_sync(cr)

    return cr


def _apply_highlight_sync(cr: CodeRenderable) -> None:
    content = cr._code_content
    filetype = cr._filetype
    client = cr._tree_sitter_client

    result = _run_sync(client.highlight_once, content, filetype)
    if result is None:
        return

    highlights = (result or {}).get("highlights", []) or []
    if not highlights:
        return

    cr._highlight_snapshot_id += 1
    snapshot_id = cr._highlight_snapshot_id

    cr._is_highlighting = False
    cr._highlights_dirty = False
    cr.mark_dirty()

    _apply_native_highlights(cr, content, highlights)

    # Build line highlights for selection/copy support
    cr._build_line_highlights(content, highlights)


def _visible_pos(content: str, pos: int) -> int:
    """Convert original-character position to visible-character position.

    ``add_highlight_by_char_range`` uses visible-character indexing
    (``\\n`` excluded), while tree-sitter highlight positions are in
    original-character indexing (``\\n`` included).  Subtract one for every
    newline before *pos* to align the two.
    """
    return pos - content[:pos].count("\n")


def _apply_native_highlights(
    cr: CodeRenderable, content: str, highlights: list
) -> None:
    from opentui.native import _nb

    tb_ptr = cr._text_buffer._ptr
    ss = cr._syntax_style

    # Reset default foreground to white
    _nb.text_buffer.text_buffer_set_default_fg(tb_ptr, [1.0, 1.0, 1.0, 1.0])

    # Create native syntax style
    native_ss = _nb.text_buffer.create_syntax_style()

    _rgba_to_list = lambda c: [float(c.r), float(c.g), float(c.b), float(c.a)]

    native_ids = {}

    for hl in highlights:
        start, end, group = hl[0], hl[1], hl[2]
        if start >= end:
            continue

        if group not in native_ids:
            style_def = ss.get_style(group)
            fg = _rgba_to_list(style_def.fg) if style_def and style_def.fg else None
            bg = _rgba_to_list(style_def.bg) if style_def and style_def.bg else None
            attrs = 0
            if style_def:
                if style_def.bold:
                    attrs |= 1
                if style_def.italic:
                    attrs |= 2
                if style_def.underline:
                    attrs |= 4
                if style_def.dim:
                    attrs |= 8
            native_ids[group] = _nb.text_buffer.syntax_style_register(
                native_ss, group, fg, bg, attrs
            )

    _nb.text_buffer.text_buffer_set_syntax_style(tb_ptr, native_ss)

    for hl in highlights:
        start, end, group = hl[0], hl[1], hl[2]
        if start >= end:
            continue
        vis_start = _visible_pos(content, start)
        vis_end = _visible_pos(content, end)
        _nb.text_buffer.text_buffer_add_highlight_by_char_range(
            tb_ptr, vis_start, vis_end, native_ids[group]
        )


def _run_sync(fn, *args):
    try:
        result = fn(*args)
    except Exception:
        return None

    if asyncio.iscoroutine(result):
        return _run_coro(result)
    return result


def _run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    except Exception:
        return None
    return None
