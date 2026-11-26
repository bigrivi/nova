"""Nova compatibility wrappers around novakit's pure compaction policy."""

from __future__ import annotations

import logging
from pathlib import Path

from novakit.compaction.policy import (
    SNIP_MARKER,
    CompactionPlan,
    find_split_point,
    first_safe_boundary,
)
from novakit.compaction.policy import compaction_threshold as _compaction_threshold
from novakit.compaction.policy import (
    estimate_context_tokens as _estimate_context_tokens,
)
from novakit.compaction.policy import estimate_tokens as _estimate_tokens
from novakit.compaction.policy import evaluate_compaction as _evaluate_compaction
from novakit.compaction.policy import should_compact as _should_compact
from novakit.compaction.policy import snip_old_tool_results as _snip_old_tool_results

from nova.llm.tokenizer import NovaTokenResolver, resolve_context_limit
from nova.settings import get_settings

log = logging.getLogger(__name__)


class _PolicyResolver(NovaTokenResolver):
    """Resolver whose context lookup remains patchable at this module's seam."""

    def context_limit(self, model: str, provider: str) -> int:
        return get_context_limit(model, provider)


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
    return _estimate_tokens(messages, model, resolver=NovaTokenResolver())


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
        resolver=NovaTokenResolver(),
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


def should_compact(total_tokens: int, model_max_tokens: int) -> bool:
    """Return whether token pressure requires compaction.

    Args:
        total_tokens: Estimated absolute context size.
        model_max_tokens: Raw provider context window.

    Returns:
        True when the configured threshold is reached.
    """
    return _should_compact(
        total_tokens,
        model_max_tokens,
        get_settings().compaction.to_compaction_config(),
    )


def evaluate_compaction(
    session_id: str,
    messages: list,
    last_compacted_at: int | None,
    model: str = "gpt-4o",
    provider: str = "ollama",
    force: bool = False,
) -> CompactionPlan:
    """Build a pure compaction plan using Nova's settings and model resolver.

    Args:
        session_id: Session being planned.
        messages: Current visible history.
        last_compacted_at: Last successful compaction time.
        model: Model id to plan against.
        provider: Provider the model runs on.
        force: Skip token pressure after a provider overflow rejection.

    Returns:
        A plan describing whether and where history can be compacted.
    """
    return _evaluate_compaction(
        session_id,
        messages,
        last_compacted_at,
        model,
        provider,
        force=force,
        config=get_settings().compaction.to_compaction_config(),
        resolver=_PolicyResolver(),
    )


def snip_old_tool_results(
    messages: list,
    max_chars: int = 2000,
    preserve_last_n_messages: int = 12,
    tool_output_token_budget: int = 50000,
    offload_dir: str | None = None,
) -> list:
    """Trim old tool output, optionally offloading full text beneath a directory.

    Args:
        messages: History to trim in place.
        max_chars: Maximum characters kept per trimmed tool result.
        preserve_last_n_messages: Newest messages exempt while within budget.
        tool_output_token_budget: Reverse token budget for intact tool output.
        offload_dir: Nova-owned directory for full tool output, if any.

    Returns:
        The same messages list with old tool results trimmed.
    """

    def sink(message_id: str, content: str) -> str | None:
        return offload_tool_output(offload_dir, message_id, content)

    return _snip_old_tool_results(
        messages,
        max_chars=max_chars,
        preserve_last_n_messages=preserve_last_n_messages,
        tool_output_token_budget=tool_output_token_budget,
        sink=sink if offload_dir else None,
        resolver=NovaTokenResolver(),
    )


def offload_tool_output(
    offload_dir: str | None,
    message_id: str,
    content: str,
) -> str | None:
    """Write full tool output to Nova's host-owned offload directory.

    Args:
        offload_dir: Directory chosen by the host, or None to skip offloading.
        message_id: Message identifier used as the filename.
        content: Full tool output to persist.

    Returns:
        Path to the offloaded text, or None when offloading is skipped or fails.
    """
    if not offload_dir or not message_id:
        return None
    try:
        directory = Path(offload_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{message_id}.txt"
        path.write_text(content, encoding="utf-8")
        return str(path)
    except OSError as error:
        log.warning("[Compaction] could not offload tool output: %s", error)
        return None


__all__ = [
    "SNIP_MARKER",
    "CompactionPlan",
    "compaction_threshold",
    "estimate_context_tokens",
    "estimate_tokens",
    "evaluate_compaction",
    "find_split_point",
    "first_safe_boundary",
    "get_context_limit",
    "offload_tool_output",
    "should_compact",
    "snip_old_tool_results",
]
