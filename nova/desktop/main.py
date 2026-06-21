from __future__ import annotations

import sys
from typing import Optional

import webview

from nova.desktop.server_thread import ServerThread
from nova.license.activation import build_activation_page
from nova.license.validator import validate
from nova.settings import Settings


def run_desktop(settings: Optional[Settings] = None, dev: bool = False) -> None:
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

    status = validate()
    if status.is_valid:
        window = webview.create_window("Nova", url=url, width=1200, height=800, min_size=(800, 600), resizable=True)
    else:
        html, api_cls = build_activation_page(url)
        window = webview.create_window("Nova", html=html, width=500, height=420, resizable=False, js_api=api_cls())

    try:
        webview.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
