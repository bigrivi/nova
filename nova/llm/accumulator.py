"""Accumulated stream state plus the shared runaway-output guard.

The runaway ceilings exist because a model stuck in a repetition loop can stream
deltas without end (an observed incident, a Qwen3.8-27B-FP8 repetition loop,
grew RSS to 4-7 GB). Exceeding a ceiling raises :class:`RunawayOutput`, which
the stream driver turns into an ``Error`` (not a ``Done``) so the runaway text
never enters message history.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


class RunawayOutput(Exception):
    """A stream exceeded a runaway ceiling; the turn must end with an ``Error``.

    Attributes:
        message: User-facing text, matched byte-for-byte to what each provider
            produced before the refactor.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class StreamAccumulator:
    """Text and token totals gathered across one streaming turn.

    Tool-call assembly stays in each provider's parser, because the state shape
    and the yield timing differ per wire format. This holds only what every
    provider accumulates the same way - the answer text and the usage totals -
    plus the two runaway guards they share.

    Attributes:
        content: Text streamed so far.
        tokens_input: Prompt tokens, when the vendor reports them.
        tokens_output: Completion tokens, when the vendor reports them.
        cache_read_tokens: Prompt-cache hits, when the vendor reports them.
        provider_meta: Opaque per-vendor state for the terminal event.
    """

    def __init__(
        self,
        model: str,
        max_content_chars: Optional[int],
        max_tool_arg_chars: Optional[int],
    ) -> None:
        self._model = model
        self._max_content_chars = max_content_chars
        self._max_tool_arg_chars = max_tool_arg_chars
        self.content = ""
        self.tokens_input: Optional[int] = None
        self.tokens_output: Optional[int] = None
        self.cache_read_tokens: Optional[int] = None
        self.provider_meta: Optional[dict] = None

    def add_text(self, text: str) -> None:
        """Append streamed text, guarding the content ceiling.

        Args:
            text: Delta to append.

        Raises:
            RunawayOutput: Appending would exceed the content ceiling. The text
                is not appended, matching the pre-refactor check-before-append.
        """
        if (
            self._max_content_chars is not None
            and len(self.content) + len(text) > self._max_content_chars
        ):
            log.error(
                "stream runaway content: model=%s size=%s exceeds %s",
                self._model,
                len(self.content) + len(text),
                self._max_content_chars,
            )
            raise RunawayOutput(
                f"model {self._model} produced runaway/unbounded output "
                f"(>{self._max_content_chars} chars), stream aborted"
            )
        self.content += text

    def guard_tool_args(self, size: int) -> None:
        """Guard the tool-argument ceiling after a parser appended arguments.

        Args:
            size: Total length of the tool call's arguments after appending.

        Raises:
            RunawayOutput: ``size`` exceeds the tool-argument ceiling.
        """
        if self._max_tool_arg_chars is not None and size > self._max_tool_arg_chars:
            log.error(
                "stream runaway tool args: model=%s size=%s exceeds %s",
                self._model,
                size,
                self._max_tool_arg_chars,
            )
            raise RunawayOutput(
                f"model {self._model} produced runaway/unbounded tool arguments "
                f"output (>{self._max_tool_arg_chars} chars), stream aborted"
            )


__all__ = ["RunawayOutput", "StreamAccumulator"]
