from __future__ import annotations

import sys

import webview

from nova.desktop.macos_chrome import wire_hidden_titlebar
from nova.desktop.server_thread import ServerThread
from nova.settings import Settings, configure_logging


def _window_url(host: str, port: int) -> str:
    # A wildcard bind is not a loadable address: WebKit refuses to navigate
    # to 0.0.0.0/:: and shows a blank window, so point the embedded view at
    # loopback. LAN browsers keep using the real address.
    if host in ("0.0.0.0", "::"):
        return f"http://127.0.0.1:{port}"
    return f"http://{host}:{port}"


def run_desktop(settings: Settings | None = None, dev: bool = False) -> None:
    settings = settings or Settings.load_config()

    # The desktop launch path never went through __main__, so without this the
    # root logger has no handler at all: the server thread runs in-process, and
    # everything it logs falls through to logging.lastResort, which only emits
    # WARNING+ to a stderr the packaged app has no console for. The result was a
    # desktop app that wrote nothing to logs/nova.log while the CLI did.
    configure_logging(settings)

    server = ServerThread(settings)
    server.start()

    if not server.wait_until_ready():
        print("[desktop] Failed to start backend server", file=sys.stderr)
        sys.exit(1)

    if dev:
        url = "http://localhost:5173"
        print(f"[desktop] Dev mode: frontend at {url}, backend at {server.host}:{server.port}")
    else:
        url = _window_url(server.host, server.port)
        print(f"[desktop] Backend ready at {url}")

    window = webview.create_window("Nova", url=url, width=1200, height=800, min_size=(800, 600), resizable=True, text_select=True)
    wire_hidden_titlebar()

    try:
        webview.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
