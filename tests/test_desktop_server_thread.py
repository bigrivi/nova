"""The desktop window joins the backend that is already running.

The window used to start its own server on a fixed port and exit when it could
not, so opening it beside a TUI left two backends and two schedulers on the same
database. It now asks the shared backend for its address first.
"""

from __future__ import annotations

from nova.desktop import server_thread as server_thread_module
from nova.desktop.server_thread import ServerThread
from nova.settings import Settings


def test_the_desktop_joins_a_backend_that_is_already_running(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path))
    settings = Settings.load_config()

    async def fake_run_server(*, settings, on_ready, on_server):
        on_ready("http://127.0.0.1:51999")

    monkeypatch.setattr(server_thread_module, "run_server", fake_run_server)

    server = ServerThread(settings)
    server.start()

    assert server.wait_until_ready(timeout=5) is True
    assert server.url == "http://127.0.0.1:51999"
    # Nothing to stop: the backend this window points at belongs to another
    # process.
    assert server.server is None
    server.stop()


def test_the_desktop_reports_no_address_when_no_backend_answers(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path))
    settings = Settings.load_config()

    async def failing_run_server(**kwargs):
        raise SystemExit(1)

    monkeypatch.setattr(server_thread_module, "run_server", failing_run_server)

    server = ServerThread(settings)
    server.start()

    assert server.wait_until_ready(timeout=0.2) is False
    assert server.url is None
