"""Verify browser-style zoom works on the built Nova frontend.

Serves frontend/dist statically, loads it in Chromium, and asserts that
Cmd/Ctrl+=/-/0 shortcuts and Ctrl+wheel apply CSS zoom on the <html> root,
and that the level persists across reload.
"""

import http.server
import os
import socketserver
import sys
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "..", "frontend", "dist")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve() -> str:
    os.chdir(DIST)
    handler = lambda *a, **kw: QuietHandler(*a, directory=DIST, **kw)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/index.html"


def expect_zoom(page, expected: float) -> None:
    # Poll instead of asserting once: synthesized key events can be delivered
    # slightly after the browser processes the previous action.
    page.wait_for_function(
        "expected => parseFloat(document.documentElement.style.zoom || '1') === expected",
        arg=expected,
        timeout=3000,
    )


def main() -> int:
    url = serve()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        # Stub the backend API so the app settles into a quiet state after
        # bootstrap; real API responses arriving mid-test made key delivery
        # racy against React re-renders.
        page.route(
            "**/api/models",
            lambda r: r.fulfill(
                status=200, content_type="application/json", body='{"items":[]}'
            ),
        )
        page.route(
            "**/api/providers",
            lambda r: r.fulfill(
                status=200, content_type="application/json", body='{"items":[]}'
            ),
        )
        page.route(
            "**/api/sessions",
            lambda r: r.fulfill(
                status=200, content_type="application/json", body='{"items":[]}'
            ),
        )
        page.route(
            "**/api/agents/**",
            lambda r: r.fulfill(
                status=200, content_type="application/json", body="{}"
            ),
        )
        page.goto(url, wait_until="networkidle")
        # networkidle can fire before React attaches the zoom listeners.
        page.wait_for_function(
            "document.getElementById('root').children.length > 0"
        )

        # Cmd + "=" zooms in by 0.1
        page.keyboard.press("Meta+=")
        expect_zoom(page, 1.1)

        # Shift variant (Cmd + "+") zooms in again
        page.keyboard.press("Meta+Shift+=")
        expect_zoom(page, 1.2)

        # Cmd + "-" zooms out
        page.keyboard.press("Meta+-")
        expect_zoom(page, 1.1)

        # Ctrl + "0" resets to 100%
        page.keyboard.press("Control+0")
        expect_zoom(page, 1.0)

        # Ctrl + wheel zooms in (deltaY < 0). Playwright's mouse.wheel cannot
        # carry modifiers, so dispatch a synthetic WheelEvent with ctrlKey.
        page.evaluate(
            "window.dispatchEvent(new WheelEvent('wheel', "
            "{deltaY: -120, ctrlKey: true, bubbles: true, cancelable: true}))"
        )
        expect_zoom(page, 1.1)
        page.evaluate(
            "window.dispatchEvent(new WheelEvent('wheel', "
            "{deltaY: 120, ctrlKey: true, bubbles: true, cancelable: true}))"
        )
        expect_zoom(page, 1.0)

        # Clamp at MAX (2.0): hammer zoom in
        for _ in range(20):
            page.keyboard.press("Meta+=")
        expect_zoom(page, 2.0)

        # Clamp at MIN (0.5): hammer zoom out
        for _ in range(40):
            page.keyboard.press("Meta+-")
        expect_zoom(page, 0.5)

        # Persistence: reload restores the stored level
        page.reload(wait_until="networkidle")
        page.wait_for_function(
            "document.getElementById('root').children.length > 0"
        )
        expect_zoom(page, 0.5)

        # Reset and confirm persistence of 1.0
        page.keyboard.press("Control+0")
        page.reload(wait_until="networkidle")
        page.wait_for_function(
            "document.getElementById('root').children.length > 0"
        )
        expect_zoom(page, 1.0)

        # Non-zoom shortcuts (Cmd+C) must not change zoom
        page.keyboard.press("Meta+c")
        expect_zoom(page, 1.0)

        browser.close()
    print("ALL ZOOM CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())