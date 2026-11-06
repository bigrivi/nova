"""Who counts as a local client, judged from the request rather than from the peer.

The loopback exemption lets the desktop app and the TUI skip credentials. The
previous rule trusted the TCP peer and the presence of a forwarding header, which
is wrong behind a same-host reverse proxy that forwards neither. These cases pin
the three signals ``is_loopback`` now requires.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova.server.auth import BasicAuthMiddleware, is_loopback


def _scope(peer="127.0.0.1", headers=None):
    return {
        "type": "http",
        "client": (peer, 40000) if peer else None,
        "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()],
    }


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "127.0.0.1:8765"},
        {"host": "localhost:5173"},
        {"host": "localhost"},
        {"host": "[::1]:8765"},
        {"host": "127.0.0.1:8765", "x-forwarded-for": "127.0.0.1"},
    ],
)
def test_local_peer_asking_for_a_local_name_is_local(headers):
    assert is_loopback(_scope(headers=headers))


@pytest.mark.parametrize(
    "peer, headers",
    [
        # A remote peer is never local, whatever it claims.
        ("192.168.1.50", {"host": "127.0.0.1:8765"}),
        (None, {"host": "127.0.0.1:8765"}),
        # A same-host proxy forwarding the public name is a remote client.
        ("127.0.0.1", {"host": "nova.example.com"}),
        # Any identity header a proxy adds means the peer is not the client.
        ("127.0.0.1", {"host": "127.0.0.1:8765", "x-real-ip": "203.0.113.9"}),
        ("127.0.0.1", {"host": "127.0.0.1:8765", "forwarded": "for=203.0.113.9"}),
        ("127.0.0.1", {"host": "127.0.0.1:8765", "x-forwarded-for": "203.0.113.9"}),
        # No Host header at all is not evidence of a local client.
        ("127.0.0.1", {}),
    ],
)
def test_anything_else_is_remote(peer, headers):
    assert not is_loopback(_scope(peer=peer, headers=headers))


def test_a_proxy_that_forwards_the_public_host_is_refused_end_to_end(
    monkeypatch, tmp_path
):
    import json

    from nova.settings import Settings

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {},
                "server": {"auth_user": "nova", "auth_password": "s3cret"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))

    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)
    app.state.settings = Settings.load_config()

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(app, client=("127.0.0.1", 40000))

    local = client.get("/api/ping", headers={"host": "127.0.0.1:8765"})
    proxied = client.get("/api/ping", headers={"host": "nova.example.com"})

    assert local.status_code == 200
    assert proxied.status_code == 401
