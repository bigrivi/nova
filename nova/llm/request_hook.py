"""Run a user request-hook script to supply dynamic request headers.

Protocol: the hook script receives ``{"session_id": ...}`` as JSON on stdin
and must print ``{"headers": {name: value}}`` as JSON on stdout with exit 0.
Anything else (missing file, timeout, nonzero exit, bad JSON) raises
RequestHookError and fails the request. Results are cached per session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK_TIMEOUT_S = 5
_MAX_CACHED_SESSIONS = 2000

_cache: dict[tuple[str, str], dict[str, str]] = {}


class RequestHookError(RuntimeError):
    """A request hook failed; the calling request must not be sent."""


def resolve_hook_path(raw: object) -> str | None:
    """Resolve a configured hook path (absolute, ``~``, or NOVA_HOME-relative)."""
    if not raw or not str(raw).strip():
        return None
    path = Path(str(raw).strip()).expanduser()
    if not path.is_absolute():
        home = Path(os.getenv("NOVA_HOME", Path.home() / ".nova")).expanduser()
        path = home / path
    return str(path)


def _hook_command(hook_path: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--_run-code", hook_path]
    return [sys.executable, hook_path]


def _evict_if_needed() -> None:
    while len(_cache) >= _MAX_CACHED_SESSIONS:
        _cache.pop(next(iter(_cache)))


def run_request_hook(hook_path: str, session_id: str | None,
                     timeout: int = HOOK_TIMEOUT_S) -> dict[str, str]:
    """Run the hook once and return its headers. No caching."""
    resolved = resolve_hook_path(hook_path)
    if not resolved:
        raise RequestHookError("request hook path is empty")
    payload = {"session_id": session_id}
    try:
        proc = subprocess.run(
            _hook_command(resolved),
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            **({"start_new_session": True} if sys.platform != "win32"
               else {"creationflags": subprocess.CREATE_NO_WINDOW}),
        )
    except FileNotFoundError as e:
        raise RequestHookError(f"request hook not found: {resolved}") from e
    except subprocess.TimeoutExpired as e:
        raise RequestHookError(
            f"request hook timed out after {timeout}s: {resolved}") from e
    except OSError as e:
        raise RequestHookError(f"request hook failed to start: {e}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[-500:]
        raise RequestHookError(
            f"request hook exited {proc.returncode}: {resolved}"
            + (f": {detail}" if detail else ""))
    if not (proc.stdout or "").strip():
        raise RequestHookError(f"request hook printed no output: {resolved}")
    try:
        data = json.loads(proc.stdout)
    except ValueError as e:
        raise RequestHookError(
            f"request hook output is not JSON: {resolved}") from e
    if not isinstance(data, dict) or not isinstance(data.get("headers", {}), dict):
        raise RequestHookError(
            f"request hook must print {{\"headers\": {{...}}}}: {resolved}")
    return {str(k): str(v) for k, v in data["headers"].items()}


def run_session_hook(hook_path: str, session_id: str | None,
                     timeout: int = HOOK_TIMEOUT_S) -> dict[str, str]:
    """Run the hook for a session, returning its headers (cached per session)."""
    resolved = resolve_hook_path(hook_path)
    if not resolved:
        raise RequestHookError("request hook path is empty")
    key = (resolved, session_id or "")
    cached = _cache.get(key)
    if cached is not None:
        return dict(cached)
    headers = run_request_hook(resolved, session_id, timeout)
    _evict_if_needed()
    _cache[key] = headers
    return dict(headers)
