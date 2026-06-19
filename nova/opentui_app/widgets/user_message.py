from opentui import Box, Text, component
from ..colors import PRIMARY, SURFACE, TEXT_NORMAL


@component
def UserMessage(text: str, *, key: str = "") -> Box:
    return Box(
        Box(
            Text(f" {text}", fg=TEXT_NORMAL),
            background_color=SURFACE,
            flex_direction="column",
            flex_grow=1,
            padding_top=1,
            padding_bottom=1,
        ),
        border=True,
        border_style="heavy",
        border_left=True,
        border_right=False,
        border_top=False,
        border_bottom=False,
        border_color=PRIMARY,
        flex_direction="row",
        key=key,
    )
