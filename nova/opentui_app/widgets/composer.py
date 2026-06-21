from opentui import Box
from ..colors import PRIMARY, SURFACE, TEXT_BRIGHT, TEXT_DIM
from .textarea import _ChatTextarea, _CUSTOM_BINDINGS


class Composer:
    def __init__(self, *, on_submit, on_change=None, key: str = "") -> None:
        textarea = _ChatTextarea(
            placeholder="Type a message...",
            placeholder_color=TEXT_DIM,
            key_bindings=_CUSTOM_BINDINGS,
            on_submit=on_submit,
            on_change=on_change,
            wrap_mode="word",
            height=1,
            focused_text_color=TEXT_BRIGHT,
            cursor_color=TEXT_BRIGHT,
        )
        textarea._focused = True

        content = Box(
            textarea,
            background_color=SURFACE,
            flex_grow=1,
            padding_left=2,
            padding_top=1,
        )
        self.box = Box(
            content,
            border=True,
            border_style="heavy",
            border_left=True,
            border_right=False,
            border_top=False,
            border_bottom=False,
            border_color=PRIMARY,
            flex_direction="row",
            height=3,
            key=key,
        )
        self.textarea = textarea
        textarea._wrapper_box = self.box
        textarea.height = 1
