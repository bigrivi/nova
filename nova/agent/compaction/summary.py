"""Summary prompt construction and the summariser call."""

from __future__ import annotations

from novakit.compaction.summary import (
    CONTINUATION_INSTRUCTION,
    NEW_SUMMARY_ANCHOR,
    PREVIOUS_SUMMARY_ANCHOR,
    SUMMARY_MESSAGE_MAX_CHARS,
    SUMMARY_PROMPT_TEMPLATE,
    SUMMARY_SYSTEM_PROMPT,
    format_for_summary,
    generate_summary,
)

__all__ = [
    "CONTINUATION_INSTRUCTION",
    "NEW_SUMMARY_ANCHOR",
    "PREVIOUS_SUMMARY_ANCHOR",
    "SUMMARY_MESSAGE_MAX_CHARS",
    "SUMMARY_PROMPT_TEMPLATE",
    "SUMMARY_SYSTEM_PROMPT",
    "format_for_summary",
    "generate_summary",
]
