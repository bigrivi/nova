from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from prompt_toolkit.completion import Completer, Completion

from nova.cli.commands import CommandRegistry

if TYPE_CHECKING:
    from prompt_toolkit.document import Document as PTDocument
else:
    PTDocument = Any


class CommandCompleter(Completer):
    def __init__(
        self,
        registry: CommandRegistry,
        load_candidates_provider: Callable[[], list[dict[str, Any]]] | None = None,
    ):
        self._registry = registry
        self._load_candidates_provider = load_candidates_provider or (lambda: [])

    def get_completions(self, document: "PTDocument", complete_event):
        text = document.text_before_cursor
        if not text or text.lstrip() != text:
            return

        normalized = text[1:] if text.startswith("/") else text
        if not normalized:
            return

        command_name, separator, remainder = normalized.partition(" ")
        if command_name == "load" and separator:
            yield from self._complete_load_argument(text, remainder)
            return
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

    def _complete_load_argument(self, raw_text: str, argument_prefix: str):
        prefix = argument_prefix.strip()
        replacement_prefix = raw_text[: len(raw_text) - len(argument_prefix)]
        normalized_prefix = prefix.casefold()

        for index, session in enumerate(self._load_candidates_provider(), start=1):
            candidate = str(index)
            title = str(session.get("title") or "Untitled").strip() or "Untitled"
            normalized_title = title.casefold()
            if prefix and not (
                candidate.startswith(prefix)
                or normalized_prefix in normalized_title
            ):
                continue

            session_id = str(session.get("id") or "").strip()
            meta = title if not session_id else f"{title} [{session_id[:8]}]"
            yield Completion(
                text=f"{replacement_prefix}{candidate}",
                start_position=-len(raw_text),
                display=candidate,
                display_meta=meta,
            )
