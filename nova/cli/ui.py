from __future__ import annotations

import select
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable


@dataclass(frozen=True)
class ModelGroup:
    provider: str
    models: list[str]


@dataclass(frozen=True)
class ModelSelection:
    provider: str
    model: str


@dataclass(frozen=True)
class SessionSelection:
    session_id: str


def _truncate_label(text: str, width: int) -> str:
    value = str(text or "").strip() or "Untitled"
    if len(value) <= width:
        return value.ljust(width)
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def _format_relative_time(timestamp_ms: int, now_ts: float | None = None) -> str:
    if timestamp_ms <= 0:
        return "unknown"
    now = int(now_ts if now_ts is not None else time.time())
    delta_seconds = max(0, now - (timestamp_ms // 1000))
    if delta_seconds < 60:
        return "just now"
    if delta_seconds < 3600:
        minutes = delta_seconds // 60
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} ago"
    if delta_seconds < 86400:
        hours = delta_seconds // 3600
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} ago"
    if delta_seconds < 604800:
        days = delta_seconds // 86400
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} ago"
    return datetime.fromtimestamp(timestamp_ms // 1000).strftime("%m-%d")


class EscapeKeyMonitor:
    """Watch stdin for a plain Escape press while streaming output."""

    def __init__(self, on_escape: Callable[[], None], poll_interval: float = 0.05):
        self._on_escape = on_escape
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._thread is not None or not sys.stdin.isatty():
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._thread is None:
            return

        self._stop_event.set()
        self._thread.join(timeout=1)
        self._thread = None

    def _run(self) -> None:
        if sys.platform == "win32":
            self._run_windows()
            return
        self._run_posix()

    def _run_posix(self) -> None:
        import termios
        import tty

        fd = sys.stdin.fileno()
        try:
            original_attrs = termios.tcgetattr(fd)
        except termios.error:
            return

        try:
            tty.setcbreak(fd)
            while not self._stop_event.is_set():
                readable, _, _ = select.select(
                    [fd], [], [], self._poll_interval)
                if not readable:
                    continue
                char = sys.stdin.read(1)
                if char != "\x1b":
                    continue
                if self._consume_escape_sequence(fd):
                    continue
                self._on_escape()
                return
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, original_attrs)
            except termios.error:
                pass

    def _consume_escape_sequence(self, fd: int) -> bool:
        """Ignore multi-byte escape sequences such as arrow keys."""
        time.sleep(0.03)
        readable, _, _ = select.select([fd], [], [], 0)
        if not readable:
            return False
        while readable:
            sys.stdin.read(1)
            readable, _, _ = select.select([fd], [], [], 0)
        return True

    def _run_windows(self) -> None:
        import msvcrt

        while not self._stop_event.is_set():
            if not msvcrt.kbhit():
                time.sleep(self._poll_interval)
                continue
            char = msvcrt.getwch()
            if char == "\x1b":
                self._on_escape()
                return
