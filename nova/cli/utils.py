from __future__ import annotations

import os
import shutil
import sys
from typing import Optional


def user_history_block_width() -> int:
    return max(shutil.get_terminal_size(fallback=(170, 24)).columns, 20)


def looks_like_error_message(text: object) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped:
        return False
    return stripped.lower().startswith("error:")


def parse_done_payload(payload: object) -> tuple[Optional[str], Optional[str]]:
    if isinstance(payload, dict):
        reason = payload.get("reason")
        content = payload.get("content")
        return (
            reason if isinstance(reason, str) else None,
            content if isinstance(content, str) else None,
        )
    if isinstance(payload, str):
        return None, payload
    return None, None


def parse_error_payload(payload: object) -> tuple[Optional[str], Optional[str]]:
    if isinstance(payload, dict):
        reason = payload.get("reason")
        message = payload.get("message")
        return (
            reason if isinstance(reason, str) else None,
            message if isinstance(message, str) else None,
        )
    if isinstance(payload, str):
        return None, payload
    return None, None


def exit_process(code: int = 130) -> None:
    """Terminate the process immediately after flushing terminal output."""
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)
