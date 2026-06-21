from opentui import Box
from opentui.structs import RGBA

BACKDROP = RGBA(0, 0, 0, 0.5)


class Modal:
    def build(self, content: Box) -> Box:
        return Box(
            content,
            position="absolute",
            left=0,
            right=0,
            bottom=0,
            top=0,
            background_color=BACKDROP,
            align_items="center",
            justify_content="center",
        )
