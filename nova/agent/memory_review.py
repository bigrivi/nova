"""Background extraction of durable facts from a finished conversation.

Runs after a turn completes and writes to long-term memory. It touches nothing
the turn loop depends on, so it stays out of the agent runtime.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from nova.llm import LLMProvider, Message as LLMMessage

log = logging.getLogger(__name__)

MIN_MESSAGES_TO_REVIEW = 4
MESSAGES_SAMPLED = 30
TOOL_CONTENT_CHARS = 200

REVIEW_PROMPT_HEADER = (
    "Review the recent conversation and extract durable facts "
    "worth remembering for future sessions.\n\n"
    "Focus on:\n"
    "- User preferences, habits, or communication style\n"
    "- Project architecture decisions or technology choices\n"
    "- Environment facts (paths, tools, configurations)\n"
    "- Recurring patterns or workflows\n\n"
    "Return a JSON array. Each entry must have:\n"
    "- key: short unique identifier (snake_case)\n"
    "- content: the full fact text\n"
    "- summary: 1-line summary\n"
    "- scope: \"user\" or \"project\" or \"session\"\n"
    "- memory_type: \"fact\" or \"preference\" or \"decision\" or \"context\"\n"
    "- tags: list of keywords\n\n"
    "Conversation:\n"
)
REVIEW_PROMPT_FOOTER = (
    "\n\nReturn ONLY valid JSON array. If nothing worth saving, "
    "return []."
)


class MemoryReviewer:
    """Asks the model which facts from a conversation deserve to be remembered."""

    def __init__(
        self,
        llm: LLMProvider,
        session: Any,
        model: str,
        data_source: Optional[Any] = None,
    ) -> None:
        self._llm = llm
        self._session = session
        self._model = model
        self._data_source = data_source

    async def run(self) -> None:
        try:
            messages = await self._session.get_messages(last_n=40)
            if len(messages) < MIN_MESSAGES_TO_REVIEW:
                return

            prompt = self._build_prompt(messages)
            result = await self._llm.chat(
                messages=[LLMMessage(role="user", content=prompt)],
                model=self._model,
            )
            facts = parse_review_facts(result.content)
            if not facts:
                return

            saved = await self._save(facts)
            if saved:
                log.info("Memory review saved %d new fact(s)", saved)
        except Exception as error:
            log.warning("Background memory review failed: %s", error)

    def _build_prompt(self, messages: list) -> str:
        lines = []
        for message in messages[-MESSAGES_SAMPLED:]:
            role = getattr(message, "role", "?")
            content = getattr(message, "content", "") or ""
            if role == "tool":
                content = content[:TOOL_CONTENT_CHARS]
            if content:
                lines.append(f"[{role}]: {content}")
        return (REVIEW_PROMPT_HEADER
                + "\n".join(lines[-MESSAGES_SAMPLED:])
                + REVIEW_PROMPT_FOOTER)

    async def _save(self, facts: list[dict]) -> int:
        from nova.memory.models import MemoryWriteRequest
        from nova.memory.service import MemoryService

        service = MemoryService(data_source=self._data_source)
        current_session = self._session.get_current_session()
        session_id = current_session.id if current_session else None

        saved = 0
        for fact in facts:
            try:
                _, created = await service.save(MemoryWriteRequest(
                    key=fact.get("key", "auto-review"),
                    content=fact.get("content", ""),
                    summary=fact.get("summary", ""),
                    scope=fact.get("scope", "user"),
                    memory_type=fact.get("memory_type", "fact"),
                    tags=fact.get("tags", []),
                    session_id=session_id,
                ))
                if created:
                    saved += 1
            except Exception as error:
                log.debug("Failed to save reviewed fact: %s", error)
        return saved


def parse_review_facts(content: str) -> list[dict]:
    """Read the fact array out of a model reply.

    Models wrap JSON in fences or surround it with prose, so a failed parse
    falls back to the outermost bracket pair before giving up.
    """
    text = (content or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        array_start = text.find("[")
        array_end = text.rfind("]")
        if array_start == -1 or array_end == -1 or array_end <= array_start:
            return []
        try:
            parsed = json.loads(text[array_start:array_end + 1])
        except json.JSONDecodeError:
            return []
    return parsed if isinstance(parsed, list) else []
