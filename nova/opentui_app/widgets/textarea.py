from opentui import Box, TextareaRenderable
from opentui.hooks import use_cursor
from opentui.input.keymapping import KeyBinding


_CUSTOM_BINDINGS: list[KeyBinding] = [
    KeyBinding(name="return", action="submit"),
    KeyBinding(name="linefeed", action="newline"),
    KeyBinding(name="return", action="newline", shift=True),
    KeyBinding(name="linefeed", action="newline", shift=True),
]


class _ChatTextarea(TextareaRenderable):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._wrapper_box: Box | None = None

    def handle_key(self, event) -> bool:
        if getattr(event, "event_type", None) == "release":
            return False
        result = super().handle_key(event)
        self._sync_height()
        return result

    def _notify_content_changed(self) -> None:
        super()._notify_content_changed()
        self._sync_height()

    def _sync_height(self) -> None:
        try:
            text = self.plain_text
            h = max(1, text.count("\n") + 1) if text else 1
            if h == getattr(self, "_cached_h", 0):
                return
            self._cached_h = h
            self.height = h
            if self._wrapper_box is not None:
                self._wrapper_box.height = h + 2
        except Exception:
            pass

    def render(self, buffer, delta_time=0):
        super().render(buffer, delta_time)
        if self._focused:
            try:
                line, col = self._edit_buffer.get_cursor_position()
            except Exception:
                line, col = 0, 0
            cx = self._x + self._padding_left + col
            cy = self._y + self._padding_top + line
            use_cursor(cx, cy)
