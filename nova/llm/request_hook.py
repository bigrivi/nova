"""Nova-compatible request hooks with NOVA_HOME-relative paths."""

from novakit.llm.request_hook import (
    HOOK_TIMEOUT_S,
    RequestHookError,
)
from novakit.llm.request_hook import (
    resolve_hook_path as _resolve_hook_path,
)
from novakit.llm.request_hook import (
    run_request_hook as _run_request_hook,
)
from novakit.llm.request_hook import (
    run_session_hook as _run_session_hook,
)

from nova.settings import nova_home


def resolve_hook_path(raw: object) -> str | None:
    """Resolve a configured hook against Nova's state directory."""
    return _resolve_hook_path(raw, nova_home())


def run_request_hook(
    hook_path: str,
    session_id: str | None,
    timeout: int = HOOK_TIMEOUT_S,
) -> dict[str, str]:
    """Run a request hook, resolving relative paths against NOVA_HOME."""
    return _run_request_hook(hook_path, session_id, timeout, base_dir=nova_home())


def run_session_hook(
    hook_path: str,
    session_id: str | None,
    timeout: int = HOOK_TIMEOUT_S,
) -> dict[str, str]:
    """Run a cached session hook with Nova's path semantics."""
    return _run_session_hook(hook_path, session_id, timeout, base_dir=nova_home())


__all__ = [
    "HOOK_TIMEOUT_S",
    "RequestHookError",
    "resolve_hook_path",
    "run_request_hook",
    "run_session_hook",
]
