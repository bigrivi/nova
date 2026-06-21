"""
Desktop application entry point.

Launches the FastAPI backend server in a background thread and opens a
PyWebView window that loads the Nova frontend.
"""

from __future__ import annotations

import sys
from typing import Optional

from nova.desktop.app import create_window, run
from nova.desktop.server_thread import ServerThread
from nova.license.activation import show_activation_dialog
from nova.license.validator import validate
from nova.settings import Settings


def run_desktop(settings: Optional[Settings] = None, dev: bool = False) -> None:
    if not dev:
        status = validate()
        if not status.is_valid:
            activated = show_activation_dialog()
            if not activated:
                sys.exit(0)

    settings = settings or Settings.load_config()

    server = ServerThread(settings)
    server.start()

    if not server.wait_until_ready():
        print("[desktop] Failed to start backend server", file=sys.stderr)
        sys.exit(1)

    if dev:
        url = "http://localhost:5173"
        print(f"[desktop] Dev mode: frontend at {url}, backend at {server.host}:{server.port}")
    else:
        url = f"http://{server.host}:{server.port}"
        print(f"[desktop] Backend ready at {url}")

    window = create_window(url)
    try:
        run(window)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
