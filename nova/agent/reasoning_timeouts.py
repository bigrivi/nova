from __future__ import annotations

REASONING_MODEL_TIMEOUTS: dict[str, int] = {
    "deepseek-r1": 600,
    "deepseek-reasoner": 600,
    "qwq": 300,
    "qwen-qwq": 300,
    "o1": 300,
    "o3": 300,
    "claude-sonnet-4": 240,
    "claude-opus-4": 240,
    "gemini-2.5-pro": 300,
    "gemini-2.5-flash": 180,
}

DEFAULT_REASONING_TIMEOUT = 600


def get_reasoning_timeout(model: str, default: int = 120) -> int:
    model_lower = model.lower()
    for key, timeout in REASONING_MODEL_TIMEOUTS.items():
        if key in model_lower:
            return timeout
    return default
