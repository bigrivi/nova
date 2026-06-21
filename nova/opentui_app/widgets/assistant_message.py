from opentui import Box
from opentui.components.markdown import MarkdownRenderable

from ..syntax_theme import default_syntax_style
from ..sync_highlighter import SyncPyTreeSitterClient
from .sync_code_block import sync_code_block


_syntax_style = default_syntax_style()
_highlighter = SyncPyTreeSitterClient()


def _render_code_node(token, ctx):
    if token.type == "code" and token.text.strip():
        return sync_code_block(
            content=token.text,
            filetype=token.lang or "",
            syntax_style=ctx.syntax_style,
            tree_sitter_client=ctx.tree_sitter_client,
        )
    return ctx.default_render()


class AssistantMessage:
    def __init__(self, *, content: str = "", key: str = "") -> None:
        self._md = MarkdownRenderable(
            content=content,
            streaming=True,
            conceal=True,
            flex_grow=1,
            syntax_style=_syntax_style,
            tree_sitter_client=_highlighter,
            render_node=_render_code_node,
        )
        self._key = key

    def build(self) -> Box:
        return Box(
            self._md,
            padding_left=2,
            padding_right=2,
            padding_top=1,
            padding_bottom=1,
            key=self._key,
            flex_direction="column",
        )
