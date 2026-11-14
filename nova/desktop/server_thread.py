from __future__ import annotations

import asyncio
import logging
import threading

from uvicorn import Server

from nova.server.app import run_server
from nova.settings import Settings

log = logging.getLogger(__name__)


class ServerThread:
    """The shared backend on a thread, for the desktop window to point at.

    It runs the same server the CLI and the TUI use, so a desktop window that
    starts while another client already serves joins that one: the thread
    reports the incumbent's address and exits.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.url: str | None = None
        self.server: Server | None = None
        self.thread: threading.Thread | None = None
        self.ready = threading.Event()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                run_server(
                    settings=self.settings,
                    on_ready=self._on_ready,
                    on_server=self._on_server,
                )
            )
        except SystemExit:
            # A port another process holds, with no incumbent to join. The
            # window reports "not ready" from wait_until_ready instead of a
            # traceback out of this thread.
            log.error("the desktop backend could not start")
        finally:
            loop.close()

    def _on_ready(self, url: str) -> None:
        self.url = url
        self.ready.set()

    def _on_server(self, server: Server) -> None:
        self.server = server

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def wait_until_ready(self, timeout: float = 15.0) -> bool:
        """Wait for an address, whether this thread serves it or joined one."""
        return self.ready.wait(timeout)

    def stop(self, timeout: float = 5.0) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=timeout)
