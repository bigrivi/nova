"""Token estimation utilities with type-aware character estimation."""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Character-to-token ratios by content type
CHARS_PER_TOKEN_TEXT = 4          # Normal messages
CHARS_PER_TOKEN_TOOL = 2          # Tool results are more token-dense
IMAGE_CHAR_ESTIMATE = 8000            # Fixed estimate for images

# CJK text tokenizes at roughly one token per character, so the Latin-oriented
# ratios above underestimate Chinese/Japanese/Korean content by 2-4x.
CHARS_PER_TOKEN_CJK = 1

# Safety margin to account for estimation inaccuracy
SAFETY_MARGIN = 1.2

_CJK_RANGES = (
    (0x3040, 0x30FF),    # Hiragana + Katakana
    (0x3400, 0x4DBF),    # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0xAC00, 0xD7AF),    # Hangul syllables
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x20000, 0x2FA1F),  # CJK Extension B-F
)


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in _CJK_RANGES)


def count_cjk_chars(text: str) -> int:
    return sum(1 for ch in text if _is_cjk(ch))


def estimate_tokens_by_type(text: str, is_tool_result: bool = False) -> int:
    """Character-based estimation with type and script awareness."""
    if not text:
        return 0
    chars_per_token = CHARS_PER_TOKEN_TOOL if is_tool_result else CHARS_PER_TOKEN_TEXT
    cjk_chars = count_cjk_chars(text)
    other_chars = len(text) - cjk_chars
    estimated = cjk_chars // CHARS_PER_TOKEN_CJK + other_chars // chars_per_token
    return max(1, estimated)


def estimate_message_tokens(message, model: str = "unknown") -> int:
    """Estimate tokens for a single message.

    Uses type-aware character estimation with safety margin.
    Optionally uses tiktoken for OpenAI models if available.
    Skips tiktoken if message contains non-text blocks (image, thinking, etc.)
    """
    # Check if message might contain non-text blocks (skip tiktoken in that case)
    content = _get_content(message)
    has_non_text = False
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ["image", "thinking", "toolCall"]:
                has_non_text = True
                break

    # Try real tokenizer first for OpenAI models (only for simple text messages)
    if not has_non_text and ("gpt" in model.lower() or "openai" in model.lower()):
        real_tokens = _estimate_with_tiktoken(message, model)
        if real_tokens is not None:
            return int(real_tokens * SAFETY_MARGIN)

    # Fallback to character estimation
    total = 0
    role = _get_role(message)

    if isinstance(content, str):
        # Distinguish tool results for estimation
        is_tool = (role == "tool")
        total += estimate_tokens_by_type(content, is_tool_result=is_tool)
    elif isinstance(content, list):
        # Handle multi-part messages (text blocks, images, etc.)
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text = block.get("text", "")
                    is_tool = (role == "tool")
                    total += estimate_tokens_by_type(text,
                                                     is_tool_result=is_tool)
                elif block.get("type") == "image":
                    total += IMAGE_CHAR_ESTIMATE // CHARS_PER_TOKEN_TEXT
                elif block.get("type") == "thinking":
                    thinking = block.get("thinking", "")
                    total += estimate_tokens_by_type(
                        str(thinking), is_tool_result=False)

    # Add tool calls tokens
    tool_calls = _get_tool_calls(message)
    for tc in tool_calls:
        if isinstance(tc, dict):
            try:
                total += estimate_tokens_by_type(
                    str(tc.get("arguments", {})),
                    is_tool_result=False
                )
            except:
                total += 32  # Fallback estimate

    # Apply safety margin
    return int(total * SAFETY_MARGIN)


def estimate_messages_tokens(messages: list, model: str = "unknown") -> int:
    """Estimate tokens for a list of messages."""
    total = 0
    for msg in messages:
        total += estimate_message_tokens(msg, model)
    return total


def _estimate_with_tiktoken(message, model: str):
    """Use tiktoken for OpenAI models if available."""
    try:
        import tiktoken
        content = _get_content(message)
        text_to_encode = ""

        if isinstance(content, str):
            text_to_encode = content
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            text_to_encode = " ".join(parts)

        if not text_to_encode:
            return None

        # Try to get encoding for specific model, fallfall to cl100k_base
        try:
            enc = tiktoken.encoding_for_model(model)
        except:
            enc = tiktoken.get_encoding("cl100k_base")

        return len(enc.encode(text_to_encode))
    except ImportError:
        return None
    except Exception:
        return None


DEFAULT_CONTEXT_WINDOW = 128000

# Exact model ids, including provider-specific tags. Checked before families.
_EXACT_CONTEXT_WINDOWS = {
    "gpt-4": 8192,
    "gpt-4-32k": 32768,
    "gpt-4-turbo": 128000,
    "gpt-3.5-turbo": 16385,
    "gpt-3.5-turbo-16k": 16385,
    "gemma2": 8192,
    "gemma4:26b": 32000,
}

# Ordered family patterns: the first substring that matches a normalised model
# id wins, so more specific entries must come first. Values are the vendor's
# advertised context window; the safety margin is applied afterwards.
_FAMILY_CONTEXT_WINDOWS = (
    # OpenAI
    ("gpt-4o", 128000),
    ("gpt-4.1", 1047576),
    ("gpt-5", 400000),
    ("o1-mini", 128000),
    ("o1", 200000),
    ("o3", 200000),
    ("o4", 200000),
    ("codex", 400000),
    # Anthropic
    ("claude-3-haiku", 200000),
    ("claude-3", 200000),
    ("claude-haiku", 200000),
    ("claude-sonnet", 200000),
    ("claude-opus", 200000),
    ("claude-fable", 1000000),
    ("claude-mythos", 1000000),
    ("claude", 200000),
    # Google
    ("gemini-1.5-pro", 2097152),
    ("gemini-1.5", 1048576),
    ("gemini-2", 1048576),
    ("gemini-3", 1048576),
    ("gemini", 1048576),
    ("gemma3", 131072),
    ("gemma4", 131072),
    ("gemma", 8192),
    # Meta
    ("muse-spark", 1048576),
    ("muse-glimmer", 1048576),
    ("muse", 1048576),
    ("llama-4", 1048576),
    ("llama4", 1048576),
    ("llama-3", 131072),
    ("llama3", 131072),
    ("llama", 131072),
    # DeepSeek
    ("deepseek-r1", 131072),
    ("deepseek-v2", 131072),
    ("deepseek-v3", 131072),
    ("deepseek-v4", 131072),
    ("deepseek", 131072),
    # Alibaba
    ("qwen3", 131072),
    ("qwen2.5", 131072),
    ("qwen2", 32768),
    ("qwen", 131072),
    # Moonshot / Zhipu / MiniMax / xAI / Mistral
    ("kimi-k2", 262144),
    ("kimi", 131072),
    ("moonshot", 131072),
    ("glm-4.6", 204800),
    ("glm-4", 131072),
    ("glm", 131072),
    ("minimax-m1", 1000000),
    ("minimax-m2", 204800),
    ("minimax-m3", 204800),
    ("minimax", 204800),
    ("grok-4", 262144),
    ("grok", 131072),
    ("mistral-large", 131072),
    ("mixtral", 32768),
    ("mistral", 32768),
    ("codestral", 262144),
    ("phi-4", 16384),
    ("command-r", 131072),
    ("nova-pro", 300000),
    ("mimo", 131072),
)

# Suffixes vendors and gateways append without changing the window.
_STRIPPABLE_SUFFIXES = (
    "-free", "-contributor", "-preview", "-latest", "-cloud", "-thinking",
)


def normalise_model_id(model: str) -> str:
    """Reduce a model id to something the family table can match.

    Gateways prefix ids with an org (``meta/muse-spark-1.2``), Ollama appends a
    size tag (``gemma4:26b``), and vendors append tier or date suffixes
    (``-free``, ``-2026-04-15``). None of those change the context window.
    """
    import re

    normalised = (model or "").strip().lower()
    if "/" in normalised:
        normalised = normalised.rsplit("/", 1)[-1]
    normalised = normalised.split("[")[0]
    normalised = normalised.split(":")[0]
    normalised = re.sub(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$", "", normalised)
    for suffix in _STRIPPABLE_SUFFIXES:
        if normalised.endswith(suffix):
            normalised = normalised[: -len(suffix)]
    return normalised.strip("-")


def resolve_context_window(model: str, provider: str) -> tuple[int, str]:
    """Return the raw context window for *model* plus where the value came from.

    Resolution order: explicit config, exact model id, model family, default.
    Configuration always wins because only the operator knows which checkpoint a
    gateway alias actually points at.
    """
    configured = _configured_context_window(model, provider)
    if configured is not None:
        return configured, "config"

    raw = (model or "").strip().lower()
    if raw in _EXACT_CONTEXT_WINDOWS:
        return _EXACT_CONTEXT_WINDOWS[raw], "exact"

    normalised = normalise_model_id(model)
    if normalised in _EXACT_CONTEXT_WINDOWS:
        return _EXACT_CONTEXT_WINDOWS[normalised], "exact"

    # An explicit 1M variant marker overrides the family default.
    if "[1m]" in raw or raw.endswith("-1m"):
        return 1000000, "variant"

    for pattern, window in _FAMILY_CONTEXT_WINDOWS:
        if pattern in normalised:
            return window, f"family:{pattern}"

    return _default_context_window(), "default"


def _configured_context_window(model: str, provider: str) -> Optional[int]:
    try:
        from nova.settings import get_settings
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


def _default_context_window() -> int:
    try:
        from nova.settings import get_settings
        configured = getattr(
            get_settings().compaction, "default_context_window", None)
    except Exception:
        return DEFAULT_CONTEXT_WINDOW
    if isinstance(configured, int) and not isinstance(configured, bool) and configured > 0:
        return configured
    return DEFAULT_CONTEXT_WINDOW


def get_context_limit_with_margin(model: str, provider: str) -> int:
    """Context limit for a model, reduced by the estimation safety margin."""
    window, source = resolve_context_window(model, provider)
    if source == "default":
        log.warning(
            "Unknown context window for model %r (provider %r); assuming %d. "
            "Set providers.%s.models.%s.limit.context in config.json to correct it.",
            model, provider, window, provider, model)
    return int(window / SAFETY_MARGIN)


# Keep existing helper functions
def _get_content(msg):
    if isinstance(msg, dict):
        return msg.get("content", "") or ""
    return getattr(msg, "content", "") or ""


def _get_role(msg):
    if isinstance(msg, dict):
        return msg.get("role", "?")
    return getattr(msg, "role", "?")


def _get_tool_calls(msg):
    if isinstance(msg, dict):
        return msg.get("tool_calls", []) or []
    return getattr(msg, "tool_calls", []) or []
