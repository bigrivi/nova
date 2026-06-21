from opentui import Box, Signal, Text
from opentui.hooks import get_renderer
from ..colors import TEXT_DIM

SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class Spinner:
    def __init__(self, *, key: str = "") -> None:
        self._frame: int = 0
        self._running: bool = False
        self._signal = Signal(0, name=f"spinner_{key}")
        self._key = key

    def start(self) -> None:
        self._running = True
        renderer = get_renderer()
        if renderer:
            renderer.request_animation_frame(self._tick)

    def stop(self) -> None:
        self._running = False

    def _tick(self, dt: float) -> None:
        if not self._running:
            return
        self._frame = (self._frame + 1) % len(SPINNER_CHARS)
        self._signal.set(self._frame)
        renderer = get_renderer()
        if renderer:
            renderer.request_animation_frame(self._tick)

    def build(self) -> Box:
        return Box(
            Text(
                lambda: f" {SPINNER_CHARS[self._signal()]} Thinking...",
                fg=TEXT_DIM,
            ),
            padding_left=2,
            padding_right=2,
            padding_top=1,
            padding_bottom=1,
            key=self._key,
            flex_direction="column",
        )
