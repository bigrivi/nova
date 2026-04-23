from __future__ import annotations

import sys
import threading
import time


class SpinnerController:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started_at: float | None = None
        self._last_render_width = 0
        self._message = "Thinking..."

    def start(self, message: str) -> None:
        if self._thread is not None and self._thread.is_alive():
            if self._message == message:
                return
            self.stop()
        self._message = message
        self._started_at = time.monotonic()
        self._last_render_width = 0
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=1)
        self._thread = None
        self._started_at = None
        clear_width = max(self._last_render_width, 1)
        sys.stderr.write("\r" + (" " * clear_width) + "\r")
        sys.stderr.flush()
        self._last_render_width = 0

    def start_llm(self) -> None:
        self.start("Thinking...")

    def start_tool(self, tool_name: str) -> None:
        self.start(f"Running {tool_name}...")

    def _run(self) -> None:
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        idx = 0
        while not self._stop_event.is_set():
            frame = chars[idx % len(chars)]
            elapsed = 0.0 if self._started_at is None else max(0.0, time.monotonic() - self._started_at)
            line = (
                f"\033[1;97m{frame} {self._message}\033[0m "
                f"\033[97m{int(elapsed)}s\033[0m "
                f"\033[37m• Esc to interrupt\033[0m "
            )
            self._last_render_width = len(line)
            sys.stderr.write(f"\r{line}")
            sys.stderr.flush()
            idx += 1
            self._stop_event.wait(0.1)
