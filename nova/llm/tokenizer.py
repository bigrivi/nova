"""Nova's settings-aware tokenizer facade over novakit's pure estimator."""

from __future__ import annotations

from novakit.llm.tokenizer import (
    CHARS_PER_TOKEN_TEXT,
    CHARS_PER_TOKEN_TOOL,
    DEFAULT_CONTEXT_WINDOW,
    count_cjk_chars,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens_by_type,
    normalise_model_id,
)
from novakit.llm.tokenizer import resolve_context_window as _resolve_context_window


def _configured_context_window(model: str, provider: str) -> int | None:
    from nova.settings import get_settings

    try:
        settings = get_settings()
    except Exception:
        return None
    provider_config = settings.providers.get(provider)
    if provider_config is None or not provider_config.models:
        return None
    model_entry = provider_config.models.get(model)
    if not isinstance(model_entry, dict):
        return None
    limit_info = model_entry.get("limit")
    if isinstance(limit_info, dict) and limit_info.get("context") is not None:
        return int(limit_info["context"])
    if model_entry.get("context_window") is not None:
        return int(model_entry["context_window"])
    return None


def _snapshot_context_window(model: str, provider: str) -> tuple[int, str] | None:
    try:
        from nova.registry.catalogue import spec_for
        from nova.settings import get_settings

        spec = spec_for(get_settings(), provider, model)
    except Exception:
        return None
    limit = spec.get("limit")
    value = limit.get("context") if isinstance(limit, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value, str(spec.get("_context_source") or "discovered")


def _default_context_window() -> int:
    from nova.settings import get_settings

    try:
        configured = getattr(get_settings().compaction, "default_context_window", None)
    except Exception:
        return DEFAULT_CONTEXT_WINDOW
    if (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and configured > 0
    ):
        return configured
    return DEFAULT_CONTEXT_WINDOW


def resolve_context_window(model: str, provider: str) -> tuple[int, str]:
    """Resolve a model window using Nova config, discovery, then novakit tables."""
    configured = _configured_context_window(model, provider)
    if configured is not None:
        return configured, "config"
    snapshot = _snapshot_context_window(model, provider)
    if snapshot is not None:
        return snapshot
    window, source = _resolve_context_window(model, provider)
    if source == "default":
        return _default_context_window(), "default"
    return window, source


def resolve_context_limit(model: str, provider: str) -> int:
    """Return Nova's planned context window without subtracting a margin."""
    import logging

    window, source = resolve_context_window(model, provider)
    if source == "default":
        logging.getLogger(__name__).warning(
            "Unknown context window for model %r (provider %r); assuming %d. "
            "Set providers.%s.models.%s.limit.context in config.json to correct it.",
            model,
            provider,
            window,
            provider,
            model,
        )
    return window


__all__ = [
    "CHARS_PER_TOKEN_TEXT",
    "CHARS_PER_TOKEN_TOOL",
    "DEFAULT_CONTEXT_WINDOW",
    "count_cjk_chars",
    "estimate_message_tokens",
    "estimate_messages_tokens",
    "estimate_tokens_by_type",
    "normalise_model_id",
    "resolve_context_limit",
    "resolve_context_window",
]
