"""Token estimation utilities with type-aware character estimation."""

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


def get_context_limit_with_margin(model: str, provider: str) -> int:
    """Return the context limit for a model, with safety margin.

    First tries to read from config.json using provider + model joint lookup:
      providers.<provider>.models.<model>.limit.context
    Falls back to hard-coded defaults.
    """
    # Try config first
    try:
        from nova.settings import get_settings
        settings = get_settings()

        if provider in settings.providers:
            provider_config = settings.providers[provider]
            if provider_config.models and model in provider_config.models:
                model_entry = provider_config.models[model]
                if isinstance(model_entry, dict):
                    # Check limit.context first
                    limit_info = model_entry.get("limit")
                    if isinstance(limit_info, dict):
                        ctx = limit_info.get("context")
                        if ctx is not None:
                            return int(int(ctx) / SAFETY_MARGIN)
                    # Check context_window directly
                    ctx = model_entry.get("context_window")
                    if ctx is not None:
                        return int(int(ctx) / SAFETY_MARGIN)
    except Exception:
        pass  # Fall back to hard-coded

    # Hard-coded defaults
    limits = {
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
        "gpt-5": 128000,
        "gpt-5.1": 128000,
        "gpt-5.2": 128000,
        "gemma4:26b": 32000,
        "minimax-m2.7:cloud": 128000,
    }
    base_limit = limits.get(model, 128000)
    return int(base_limit / SAFETY_MARGIN)


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
