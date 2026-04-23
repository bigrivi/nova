"""
Memory application service.
"""

from __future__ import annotations

import time
import uuid
import re
import json
from typing import Awaitable, Callable, Optional

from nova.llm import Message as LLMMessage
from nova.memory.models import (
    MemoryRecord,
    MemorySearchFilters,
    MemoryWriteRequest,
    VALID_MEMORY_SCOPES,
    VALID_MEMORY_TYPES,
)
from nova.memory.repository import MemoryRepository
from nova.settings import get_settings


MemoryAISelector = Callable[[str, list[MemoryRecord], int], Awaitable[list[MemoryRecord]]]


class MemoryService:
    def __init__(self, repository: Optional[MemoryRepository] = None):
        self.repository = repository or MemoryRepository()

    async def save(self, request: MemoryWriteRequest) -> tuple[MemoryRecord, bool]:
        scope = self._normalize_scope(request.scope)
        memory_type = self._normalize_memory_type(request.memory_type)
        session_id = self._normalize_session_id(scope, request.session_id)
        now = int(time.time() * 1000)
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            key=self._normalize_required_text(request.key, "key"),
            scope=scope,
            session_id=session_id,
            memory_type=memory_type,
            content=self._normalize_required_text(request.content, "content"),
            summary=self._normalize_required_text(request.summary, "summary"),
            tags=self._normalize_tags(request.tags),
            created_at=now,
            updated_at=now,
        )
        return await self.repository.upsert(record)

    async def search(
        self,
        query: str,
        scope: str = "all",
        memory_type: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 5,
        use_ai: bool = False,
        ai_selector: Optional[MemoryAISelector] = None,
    ) -> list[MemoryRecord]:
        normalized_scope = self._normalize_search_scope(scope)
        normalized_type = self._normalize_optional_memory_type(memory_type)
        normalized_session_id = self._normalize_optional_text(session_id)
        normalized_query = query.strip()
        filters = MemorySearchFilters(
            query="",
            scope=normalized_scope,
            memory_type=normalized_type,
            session_id=normalized_session_id,
            limit=max(self._normalize_limit(limit) * 10, 50),
        )
        self._validate_scope_session_pair(filters.scope, filters.session_id)
        candidates = await self.repository.list_memories(filters)
        ranked = self._rank_records(candidates, normalized_query, limit=self._normalize_limit(limit) * 3)
        if not use_ai or not ranked:
            return ranked[:self._normalize_limit(limit)]

        selector = ai_selector or self._select_with_ai
        try:
            selected = await selector(normalized_query, ranked, self._normalize_limit(limit))
        except Exception:
            return ranked[:self._normalize_limit(limit)]
        return selected[:self._normalize_limit(limit)] or ranked[:self._normalize_limit(limit)]

    async def list_memories(
        self,
        scope: str = "all",
        memory_type: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        normalized_scope = self._normalize_search_scope(scope)
        normalized_type = self._normalize_optional_memory_type(memory_type)
        normalized_session_id = self._normalize_optional_text(session_id)
        filters = MemorySearchFilters(
            scope=normalized_scope,
            memory_type=normalized_type,
            session_id=normalized_session_id,
            limit=self._normalize_limit(limit),
        )
        self._validate_scope_session_pair(filters.scope, filters.session_id)
        return await self.repository.list_memories(filters)

    async def delete(
        self,
        memory_id: Optional[str] = None,
        key: Optional[str] = None,
        scope: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        normalized_memory_id = self._normalize_optional_text(memory_id)
        if normalized_memory_id:
            return await self.repository.delete_by_id(normalized_memory_id)

        normalized_key = self._normalize_optional_text(key)
        normalized_scope = self._normalize_optional_text(scope)
        if not normalized_key or not normalized_scope:
            raise ValueError("delete_memory requires either id or key with scope")

        final_scope = self._normalize_scope(normalized_scope)
        final_session_id = self._normalize_session_id(final_scope, session_id)
        return await self.repository.delete_by_key(
            key=normalized_key,
            scope=final_scope,
            session_id=final_session_id,
        )

    def _normalize_scope(self, scope: str) -> str:
        normalized = self._normalize_required_text(scope, "scope")
        if normalized not in VALID_MEMORY_SCOPES:
            raise ValueError(f"Unsupported memory scope: {scope}")
        return normalized

    def _normalize_search_scope(self, scope: str) -> str:
        normalized = self._normalize_required_text(scope or "all", "scope")
        if normalized != "all" and normalized not in VALID_MEMORY_SCOPES:
            raise ValueError(f"Unsupported memory scope: {scope}")
        return normalized

    def _normalize_memory_type(self, memory_type: str) -> str:
        normalized = self._normalize_required_text(memory_type, "memory_type")
        if normalized not in VALID_MEMORY_TYPES:
            raise ValueError(f"Unsupported memory type: {memory_type}")
        return normalized

    def _normalize_optional_memory_type(self, memory_type: Optional[str]) -> Optional[str]:
        if memory_type is None:
            return None
        return self._normalize_memory_type(memory_type)

    def _normalize_limit(self, limit: int) -> int:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        return min(limit, 50)

    def _normalize_tags(self, tags: list[str]) -> list[str]:
        normalized: list[str] = []
        for tag in tags or []:
            text = self._normalize_optional_text(tag)
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    def _normalize_session_id(self, scope: str, session_id: Optional[str]) -> Optional[str]:
        normalized_session_id = self._normalize_optional_text(session_id)
        if scope == "session" and not normalized_session_id:
            raise ValueError("session_id is required when scope is session")
        if scope != "session":
            return None
        return normalized_session_id

    def _validate_scope_session_pair(self, scope: str, session_id: Optional[str]) -> None:
        if scope == "session" and not session_id:
            raise ValueError("session_id is required when scope is session")

    def _normalize_required_text(self, value: str, field_name: str) -> str:
        normalized = self._normalize_optional_text(value)
        if not normalized:
            raise ValueError(f"{field_name} is required")
        return normalized

    def _normalize_optional_text(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _rank_records(self, records: list[MemoryRecord], query: str, limit: int) -> list[MemoryRecord]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            return records[:limit]

        terms = self._tokenize_query(normalized_query)
        scored: list[tuple[int, int, MemoryRecord]] = []
        for record in records:
            haystack = " ".join(
                [
                    record.key,
                    record.summary,
                    record.content,
                    " ".join(record.tags),
                ]
            ).lower()
            score = 0
            if normalized_query in haystack:
                score += 10
            for term in terms:
                if term in haystack:
                    score += 3
                if term in record.summary.lower():
                    score += 2
                if term in record.key.lower():
                    score += 1
            if score > 0:
                scored.append((score, record.updated_at, record))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [record for _, _, record in scored[:limit]]

    def _tokenize_query(self, query: str) -> list[str]:
        stop_words = {
            "the", "and", "for", "with", "that", "this", "from", "into", "about",
            "please", "answer", "tell", "me", "a", "an", "to", "of", "in", "on",
            "is", "are", "be", "it", "my", "our", "your",
        }
        terms = []
        for term in re.findall(r"[a-z0-9_]+", query.lower()):
            if len(term) < 2 or term in stop_words:
                continue
            for variant in self._term_variants(term):
                if variant not in terms:
                    terms.append(variant)
        return terms

    def _term_variants(self, term: str) -> list[str]:
        variants = [term]
        if term.endswith("ly") and len(term) > 4:
            variants.append(term[:-2])
        if term.endswith("es") and len(term) > 4:
            variants.append(term[:-2])
        if term.endswith("s") and len(term) > 3:
            variants.append(term[:-1])
        return [variant for variant in variants if len(variant) >= 2]

    async def _select_with_ai(
        self,
        query: str,
        candidates: list[MemoryRecord],
        limit: int,
    ) -> list[MemoryRecord]:
        from nova.app.runtime import build_llm

        settings = get_settings()
        llm = build_llm(settings=settings)
        provider_name = settings.llm.provider.strip() or settings.provider
        model = settings.resolve_model_name(settings.model, provider_name=provider_name) or settings.model

        messages = self._build_ai_selection_messages(query, candidates, limit)
        if not messages:
            return []

        result = await llm.chat(
            messages=messages,
            model=model,
            tools=[],
        )
        selected_indices = self._parse_ai_indices(result.content)
        selected: list[MemoryRecord] = []
        for idx in selected_indices:
            if 0 <= idx < len(candidates):
                selected.append(candidates[idx])
        return selected

    def _build_ai_selection_messages(
        self,
        query: str,
        candidates: list[MemoryRecord],
        limit: int,
    ) -> list[LLMMessage]:
        manifest_lines = []
        for index, record in enumerate(candidates[: max(limit * 3, 8)]):
            tags = ", ".join(record.tags) if record.tags else "-"
            content_preview = " ".join(record.content.split())[:200]
            manifest_lines.append(
                f"{index}: key={record.key} "
                f"type={record.memory_type} scope={record.scope} "
                f"tags={tags}\n"
                f"summary: {record.summary}\n"
                f"content: {content_preview}"
            )
        if not manifest_lines:
            return []

        system = (
            "You select the most relevant saved memories for a user query.\n"
            f"Return strict JSON only, with key \"indices\" containing up to {limit} integer indices.\n"
            "Selection rules:\n"
            "1. Prefer memories whose summary or key directly matches the user's current intent.\n"
            "2. Use content only as supporting evidence or a tie-breaker.\n"
            "3. Prefer specific topical memories over generic writing-style or broad project notes.\n"
            "4. Do not select a memory just because it shares generic words with the query.\n"
            "5. Return indices in best-first order.\n"
            "If none are clearly relevant, return {\"indices\": []}."
        )
        user_content = (
            f"Query: {query}\n\n"
            "Candidates:\n"
            + "\n\n".join(manifest_lines)
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user_content),
        ]

    def _parse_ai_indices(self, content: str) -> list[int]:
        text = self._extract_json_object(content or "")
        parsed = json.loads(text)
        indices = parsed.get("indices", []) if isinstance(parsed, dict) else []
        if not isinstance(indices, list):
            return []
        result: list[int] = []
        for item in indices:
            if isinstance(item, int) and item not in result:
                result.append(item)
        return result

    def _extract_json_object(self, content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text
