from __future__ import annotations

from textual.widgets import TextArea


class ChatTextArea(TextArea):

    BINDINGS = [
        ("ctrl+enter", "newline", "New line"),
    ]

    MAX_LINES = 8

    def __init__(self) -> None:
        super().__init__(placeholder="Type a message\u2026")

    def action_newline(self) -> None:
        self.insert("\n")

    def _on_key(self, event) -> None:
        if event.key == "tab" and self.text.strip().startswith("/"):
            event.prevent_default()
            event.stop()
            self._complete_command()
            return

        if event.key == "enter":
            event.prevent_default()
            event.stop()

            text = self.text.strip()

            if text:
                self.app.handle_submit(text)
                self.clear()
                self.sync_height()

    def _complete_command(self) -> None:
        text = self.text.strip()
        partial = text[1:].lower()

        candidates = self._matching_commands(partial)
        if not candidates:
            return

        chosen = candidates[0]
        self.text = f"/{chosen}"
        if len(candidates) == 1:
            self.text += " "
        self.cursor = len(self.text)

    def _matching_commands(self, partial: str) -> list[str]:
        try:
            specs = self.app.command_specs
        except Exception:
            return []

        matches: list[str] = []
        for spec in specs:
            for name in (spec.id, *spec.aliases):
                if name.startswith(partial) and name not in matches:
                    matches.append(name)

        matches.sort(key=lambda x: (x != partial, x))
        return matches

    def on_blur(self, event) -> None:
        if getattr(self.app, '_asking', False):
            return
        self.focus()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.sync_height()

    def sync_height(self) -> None:
        lines = max(1, self.text.count("\n") + 1)

        textarea_height = min(lines, self.MAX_LINES)
        wrapper_height = textarea_height + 2

        wrap = self.app.query_one("#input-wrap")

        wrap.styles.height = wrapper_height
        self.styles.height = textarea_height
