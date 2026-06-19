from opentui import Box, component
from opentui.components.markdown import MarkdownRenderable


@component
def AssistantMessage(content: str, *, key: str = "",
                      syntax_style=None, tree_sitter_client=None,
                      render_node=None) -> Box:
    return Box(
        MarkdownRenderable(
            content=content,
            conceal=True,
            flex_grow=1,
            syntax_style=syntax_style,
            tree_sitter_client=tree_sitter_client,
            render_node=render_node,
        ),

        padding_left=2,
        padding_right=2,
        padding_top=1,
        padding_bottom=1,
        key=key,
        flex_direction="column",
    )
