from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

import httpx
import uvicorn
from uvicorn import Config, Server

from nova.server.app import create_app
from nova.settings import Settings


class ServerThread:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.server: Optional[Server] = None
        self.thread: Optional[threading.Thread] = None
        self.port: int = settings.backend_port
        self.host: str = settings.host

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = create_app(settings=self.settings)
        config = Config(
            app,
            host=self.host,
            port=self.port,
            log_level=self.settings.log_level.lower(),
        )
        self.server = Server(config)
        loop.run_until_complete(self.server.serve())

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self.server:
            self.server.should_exit = True
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)

    def wait_until_ready(self, timeout: float = 15.0) -> bool:
        url = f"http://{self.host}:{self.port}/health"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(url, timeout=2)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        return False
