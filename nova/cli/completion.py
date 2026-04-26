from __future__ import annotations

from typing import TYPE_CHECKING, Any

from prompt_toolkit.completion import Completer, Completion

from nova.cli.commands import CommandRegistry

if TYPE_CHECKING:
    from prompt_toolkit.document import Document as PTDocument
else:
    PTDocument = Any


class CommandCompleter(Completer):
    def __init__(self, registry: CommandRegistry):
        self._registry = registry

    def get_completions(self, document: "PTDocument", complete_event):
        text = document.text_before_cursor
        if not text or text.lstrip() != text:
            return

        normalized = text[1:] if text.startswith("/") else text
        if not normalized:
            return

        command_name, separator, remainder = normalized.partition(" ")
        if separator:
            return

        for spec in self._registry.specs:
            candidates = (spec.id, *spec.aliases)
            if not any(candidate.startswith(normalized) for candidate in candidates):
                continue

            replacement = f"/{spec.id}"
            display = spec.id
            meta = spec.description
            yield Completion(
                text=replacement,
                start_position=-len(text),
                display=display,
                display_meta=meta,
            )
