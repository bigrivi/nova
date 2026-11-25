"""Nova-specific defaults applied to providers implemented by novakit."""

from __future__ import annotations

from typing import Any

from nova.llm.request_hook import resolve_hook_path
from nova.llm.user_agent import default_user_agent


def nova_provider_options(options: dict[str, Any]) -> dict[str, Any]:
    """Apply Nova's User-Agent and NOVA_HOME-relative hook path semantics."""
    resolved = dict(options)
    resolved["user_agent"] = resolved.get("user_agent") or default_user_agent()
    for key in ("request_hook", "request_session_hook"):
        if resolved.get(key):
            resolved[key] = resolve_hook_path(resolved[key])
    return resolved
