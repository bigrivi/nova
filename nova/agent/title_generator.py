"""Nova compatibility facade for portable session-title generation."""

from __future__ import annotations

from novakit.agent.title import (
    MAX_TITLE_LENGTH,
    TITLE_CALL_TIMEOUT_SECONDS,
    TITLE_SYSTEM_PROMPT,
    TITLE_USER_TEMPLATE,
    build_title_messages,
    clean_title,
)
from novakit.agent.title import generate_session_title as _generate_session_title
from novakit.llm import LLMProvider

TITLE_CALL_TIMEOUT_SECONDS = TITLE_CALL_TIMEOUT_SECONDS


async def generate_session_title(
    llm: LLMProvider,
    first_message: str,
    model: str,
    session_id: str | None = None,
    tools: list[dict] | None = None,
) -> str | None:
    """Generate a title through novakit while preserving Nova's timeout seam.

    Args:
        llm: Provider used for the one-shot call.
        first_message: The session's opening user message.
        model: Model id to run the call with.
        session_id: Session identity forwarded to request hooks.
        tools: Tool schemas forwarded for gateway-compatible requests.

    Returns:
        The cleaned title, or None when generation fails.
    """
    return await _generate_session_title(
        llm,
        first_message,
        model,
        session_id=session_id,
        tools=tools,
        timeout=TITLE_CALL_TIMEOUT_SECONDS,
    )


__all__ = [
    "MAX_TITLE_LENGTH",
    "TITLE_CALL_TIMEOUT_SECONDS",
    "TITLE_SYSTEM_PROMPT",
    "TITLE_USER_TEMPLATE",
    "build_title_messages",
    "clean_title",
    "generate_session_title",
]
