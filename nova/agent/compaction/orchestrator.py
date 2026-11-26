"""Nova compatibility facade over novakit's portable compaction runtime."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from novakit.agent.compaction import CompactionError
from novakit.compaction import (
    CompactionConfig,
    CompactionStore,
    DefaultCompactor,
    TokenResolver,
    ToolOutputSink,
)
from novakit.compaction import compact as _compact
from novakit.compaction import estimate_context_tokens as _estimate_context_tokens
from novakit.compaction import estimate_tokens as _estimate_tokens
from novakit.compaction import prepare_compaction as _prepare_compaction
from novakit.compaction import run_compaction_plan as _run_compaction_plan
from novakit.compaction import snip_tool_results_in_store as _snip_tool_results_in_store
from novakit.compaction.policy import compaction_threshold as _compaction_threshold
from novakit.events import AgentEventFrame
from novakit.llm import LLMProvider
from novakit.session.models import Message, SessionContext

from nova.agent.compaction.messages import (
    compacted_at_of,
    contains_summary,
    content_of,
    created_at_of,
    id_of,
    is_summary,
    new_message_id,
    role_of,
    session_id_of,
    set_compacted_at,
    tokens_input_of,
    tokens_output_of,
    tool_call_id_of,
    tool_call_ids_of,
    tool_calls_of,
)
from nova.agent.compaction.policy import (
    SNIP_MARKER,
    CompactionPlan,
    evaluate_compaction,
    find_split_point,
    first_safe_boundary,
    offload_tool_output,
    should_compact,
    snip_old_tool_results,
)
from nova.agent.compaction.store import DataSourceCompactionStore
from nova.agent.compaction.summary import (
    CONTINUATION_INSTRUCTION,
    NEW_SUMMARY_ANCHOR,
    PREVIOUS_SUMMARY_ANCHOR,
    SUMMARY_MESSAGE_MAX_CHARS,
    SUMMARY_PROMPT_TEMPLATE,
    SUMMARY_SYSTEM_PROMPT,
    format_for_summary,
    generate_summary,
)
from nova.llm.tokenizer import NovaTokenResolver, resolve_context_limit
from nova.settings import get_settings

if TYPE_CHECKING:
    from nova.db.data_source import DataSourceProtocol

log = logging.getLogger(__name__)


class _ControllerResolver(NovaTokenResolver):
    """Resolver whose context lookup remains patchable in this module."""

    def context_limit(self, model: str, provider: str) -> int:
        return get_context_limit(model, provider)


class _ControllerStore:
    """Late-bound store used by the compatibility controller."""

    def __init__(self, store: CompactionStore | None = None) -> None:
        self._store = store

    def bind(self, store: CompactionStore) -> None:
        self._store = store

    def _delegate(self) -> CompactionStore:
        if self._store is None:
            raise RuntimeError("compaction requires a data source or store")
        return self._store

    async def update_message_content(self, message_id: str, content: str) -> None:
        await self._delegate().update_message_content(message_id, content)

    async def add_summary(
        self, session_id: str, content: str, time_created: int
    ) -> Message:
        return await self._delegate().add_summary(session_id, content, time_created)

    async def mark_messages_compacted_by_ids(
        self, session_id: str, message_ids: list[str]
    ) -> None:
        await self._delegate().mark_messages_compacted_by_ids(session_id, message_ids)

    async def update_session_compacted_at(
        self, session_id: str, timestamp: int
    ) -> None:
        await self._delegate().update_session_compacted_at(session_id, timestamp)

    async def get_messages(self, session_id: str) -> list:
        return await self._delegate().get_messages(session_id)


def get_context_limit(model: str, provider: str) -> int:
    """Return Nova's configured or discovered context window for a model.

    Args:
        model: Model id to look up.
        provider: Provider the model runs on.

    Returns:
        Context window in tokens.
    """
    return resolve_context_limit(model, provider)


def estimate_tokens(messages: list, model: str = "unknown") -> int:
    """Estimate tokens for messages in isolation.

    Args:
        messages: History to measure.
        model: Model id the estimate is planned against.

    Returns:
        Estimated token count.
    """
    return _estimate_tokens(messages, model, resolver=_ControllerResolver())


def estimate_context_tokens(
    messages: list,
    model: str = "unknown",
    compacted_at: int | None = None,
) -> int:
    """Estimate absolute context size using provider-accounting anchors.

    Args:
        messages: History to measure.
        model: Model id the estimate is planned against.
        compacted_at: Last successful compaction time.

    Returns:
        Absolute context size in tokens.
    """
    return _estimate_context_tokens(
        messages,
        model,
        compacted_at,
        resolver=_ControllerResolver(),
    )


def compaction_threshold(model_max_tokens: int) -> int:
    """Return the compaction trigger threshold for a context window.

    Args:
        model_max_tokens: Raw provider context window.

    Returns:
        Token threshold after reserving reply and summary headroom.
    """
    return _compaction_threshold(
        model_max_tokens,
        get_settings().compaction.to_compaction_config(),
    )


def _tool_output_sink(session_id: str) -> ToolOutputSink:
    settings = get_settings()
    directory = str(settings.home / "sessions" / session_id / "tool-output")

    def sink(message_id: str, content: str) -> str | None:
        return offload_tool_output(directory, message_id, content)

    return sink


def _store(db: DataSourceProtocol | None) -> CompactionStore:
    if db is None:
        raise RuntimeError("compaction requires a data source")
    return DataSourceCompactionStore(db)


async def prepare_compaction(
    session_id: str,
    messages: list,
    last_compacted_at: int | None,
    db: DataSourceProtocol | None,
    model: str = "gpt-4o",
    provider: str = "ollama",
    force: bool = False,
) -> CompactionPlan:
    """Evaluate history and run Layer 1 through Nova's persistence adapter.

    Args:
        session_id: Session being planned.
        messages: Caller-owned visible history.
        last_compacted_at: Last successful compaction time.
        db: Nova data source owning messages.
        model: Model id to plan against.
        provider: Provider the model runs on.
        force: Skip token pressure after an overflow rejection.

    Returns:
        A portable compaction plan.
    """
    return await _prepare_compaction(
        session_id,
        messages,
        last_compacted_at,
        _store(db),
        model,
        provider,
        force=force,
        config=get_settings().compaction.to_compaction_config(),
        resolver=_ControllerResolver(),
        sink=_tool_output_sink(session_id),
    )


async def run_compaction_plan(
    plan: CompactionPlan,
    db: DataSourceProtocol,
    llm: LLMProvider,
    model: str = "gpt-4o",
    provider: str = "ollama",
    messages: list | None = None,
    tools: list[dict] | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> bool:
    """Execute a prepared plan through Nova's persistence adapter.

    Args:
        plan: Plan returned by :func:`prepare_compaction`.
        db: Nova data source owning messages.
        llm: Provider used for summary generation.
        model: Model id to summarize with.
        provider: Provider the model runs on.
        messages: Caller-owned history, if already loaded.
        tools: Tool schemas forwarded to the summary request.
        on_delta: Callback receiving summary chunks.

    Returns:
        Whether history changed.
    """
    return await _run_compaction_plan(
        plan,
        _store(db),
        llm,
        model,
        provider,
        messages=messages,
        tools=tools,
        on_delta=on_delta,
        config=get_settings().compaction.to_compaction_config(),
        resolver=_ControllerResolver(),
    )


async def snip_tool_results_in_db(
    db: DataSourceProtocol, session_id: str, messages: list
) -> None:
    """Trim and persist old tool results through Nova's data source.

    Args:
        db: Nova data source owning messages.
        session_id: Session whose offload directory should be used.
        messages: Caller-owned history to trim in place.
    """
    await _snip_tool_results_in_store(
        _store(db),
        session_id,
        messages,
        config=get_settings().compaction.to_compaction_config(),
        resolver=_ControllerResolver(),
        sink=_tool_output_sink(session_id),
    )


async def compact(
    session_id: str,
    db: DataSourceProtocol,
    llm: LLMProvider,
    model: str = "gpt-4o",
    provider: str = "ollama",
    messages: list | None = None,
    split_index: int | None = None,
    tools: list[dict] | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> bool:
    """Run Layer 2 compaction through Nova's persistence adapter.

    Args:
        session_id: Session being compacted.
        db: Nova data source owning messages.
        llm: Provider used for summary generation.
        model: Model id to summarize with.
        provider: Provider the model runs on.
        messages: Caller-owned history, if already loaded.
        split_index: Explicit split, or None to choose one.
        tools: Tool schemas forwarded to the summary request.
        on_delta: Callback receiving summary chunks.

    Returns:
        Whether history changed.

    Raises:
        CompactionError: When summary generation fails.
    """
    store = _store(db)
    history = messages if messages is not None else await store.get_messages(session_id)
    config = get_settings().compaction.to_compaction_config()
    if split_index is None:
        threshold = _compaction_threshold(
            get_context_limit(model, provider),
            config,
        )
        split_index = find_split_point(
            history,
            keep_tokens=min(config.summary_keep_tokens, threshold // 2),
        )
    return await _compact(
        session_id,
        store,
        llm,
        model,
        provider,
        messages=history,
        split_index=split_index,
        tools=tools,
        on_delta=on_delta,
        config=config,
        resolver=_ControllerResolver(),
    )


class CompactionController:
    """Compatibility facade preserving Nova's existing controller interface."""

    def __init__(
        self,
        model: str,
        provider: str,
        *,
        store: CompactionStore | None = None,
        config: CompactionConfig | None = None,
        resolver: TokenResolver | None = None,
        sink: ToolOutputSink | None = None,
    ) -> None:
        """Bind a model route and optional host dependencies.

        Args:
            model: Model id to plan and summarize with.
            provider: Provider the model runs on.
            store: Optional persistence adapter; a data source may be bound later.
            config: Explicit compaction tuning, or Nova settings when omitted.
            resolver: Token/context resolver, or Nova's facade when omitted.
            sink: Optional full-tool-output offload callback.
        """
        self._store = _ControllerStore(store)
        self._config = config or get_settings().compaction.to_compaction_config()
        self._resolver = resolver or _ControllerResolver()
        self._sink = sink
        self._default = DefaultCompactor(
            model,
            provider,
            store=self._store,
            config=self._config,
            resolver=self._resolver,
            sink=self._sink,
        )

    @property
    def model(self) -> str:
        """Model id used for planning and summary generation."""
        return self._default.model

    @property
    def provider(self) -> str:
        """Provider used for context resolution."""
        return self._default.provider

    @property
    def consecutive_failures(self) -> int:
        """Current consecutive summary-failure count."""
        return self._default.consecutive_failures

    @consecutive_failures.setter
    def consecutive_failures(self, value: int) -> None:
        self._default.consecutive_failures = value

    @property
    def compacted(self) -> bool:
        """Whether the last pass changed history."""
        return self._default.compacted

    @property
    def force_next(self) -> bool:
        """Whether the next pass must ignore token pressure."""
        return self._default.force_next

    @force_next.setter
    def force_next(self, value: bool) -> None:
        self._default.force_next = value

    def summarising_allowed(self) -> bool:
        """Return whether the circuit breaker permits another summary attempt."""
        return self._default.summarising_allowed()

    def record_result(
        self,
        compacted: bool,
        session: SessionContext | dict[str, Any] | None,
    ) -> None:
        """Record one compaction outcome in the shared breaker state.

        Args:
            compacted: Whether history changed.
            session: Session stamped on success.
        """
        self._default.record_result(compacted, session)

    async def plan(
        self,
        messages: list,
        session: SessionContext | dict[str, Any] | None,
        db: DataSourceProtocol | None = None,
        force: bool = False,
    ) -> CompactionPlan | None:
        """Plan compaction while preserving Nova's legacy data-source argument.

        Args:
            messages: Caller-owned history.
            session: Active session context or row.
            db: Optional data source bound for this plan.
            force: Skip token pressure and the breaker gate.

        Returns:
            A runnable plan, or None when no summary should run.
        """
        if db is not None:
            self._store.bind(_store(db))
        plan = await prepare_compaction(
            session_id=session_id_of(session) or "",
            messages=messages,
            last_compacted_at=compacted_at_of(session),
            db=db,
            model=self.model,
            provider=self.provider,
            force=force,
        )
        if not plan.needs_compaction:
            return None
        if not force and not self.summarising_allowed():
            return None
        return plan

    async def maybe_compact(
        self,
        messages: list,
        session: SessionContext | dict[str, Any] | None,
        db: DataSourceProtocol,
        llm: LLMProvider,
        emit: Callable[..., Awaitable[None]],
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Run compaction with Nova's data source and portable event contract.

        Args:
            messages: Current visible history.
            session: Active session context or row.
            db: Nova data source owning messages.
            llm: Provider used for summary generation.
            emit: Event callback for context and compaction frames.
            tools: Tool schemas forwarded to the summary request.

        Yields:
            Context and compaction event frames.
        """
        self._store.bind(_store(db))
        if self._sink is None:
            failures = self.consecutive_failures
            was_compacted = self.compacted
            force_next = self.force_next
            self._default = DefaultCompactor(
                self.model,
                self.provider,
                store=self._store,
                config=self._config,
                resolver=self._resolver,
                sink=_tool_output_sink(session_id_of(session) or ""),
            )
            self._default.consecutive_failures = failures
            self._default.compacted = was_compacted
            self._default.force_next = force_next
        async for frame in self._default.maybe_compact(
            messages,
            session,
            llm,
            emit,
            tools=tools,
        ):
            yield frame


__all__ = [
    "CONTINUATION_INSTRUCTION",
    "NEW_SUMMARY_ANCHOR",
    "PREVIOUS_SUMMARY_ANCHOR",
    "SNIP_MARKER",
    "SUMMARY_MESSAGE_MAX_CHARS",
    "SUMMARY_PROMPT_TEMPLATE",
    "SUMMARY_SYSTEM_PROMPT",
    "CompactionController",
    "CompactionError",
    "CompactionPlan",
    "compact",
    "compacted_at_of",
    "compaction_threshold",
    "contains_summary",
    "content_of",
    "created_at_of",
    "estimate_context_tokens",
    "estimate_tokens",
    "evaluate_compaction",
    "find_split_point",
    "first_safe_boundary",
    "format_for_summary",
    "generate_summary",
    "get_context_limit",
    "id_of",
    "is_summary",
    "new_message_id",
    "offload_tool_output",
    "prepare_compaction",
    "role_of",
    "run_compaction_plan",
    "session_id_of",
    "set_compacted_at",
    "should_compact",
    "snip_old_tool_results",
    "snip_tool_results_in_db",
    "tokens_input_of",
    "tokens_output_of",
    "tool_call_id_of",
    "tool_call_ids_of",
    "tool_calls_of",
]
