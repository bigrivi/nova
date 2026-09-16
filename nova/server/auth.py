"""HTTP Basic authentication for LAN exposure.

Enabled only when both auth_user and auth_password are set in the
config.json ``server`` block. Loopback clients (desktop app, local
TUI/CLI) are exempt so local use never needs credentials. Frontend
static files are public so the login dialog can load; every /api route
requires credentials otherwise.

Deliberately omits the WWW-Authenticate header: sending it would make
browsers pop up their native login prompt instead of our custom dialog.
"""

from __future__ import annotations

import base64
import binascii
import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from nova.settings import Settings, get_settings

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})


def get_configured_credentials(
    settings: Settings | None = None,
) -> tuple[str, str] | None:
    resolved = settings if settings is not None else get_settings()
    user = (resolved.auth_user or "").strip()
    password = resolved.auth_password or ""
    if not user or not password:
        return None
    return (user, password)


def is_loopback(scope: Scope) -> bool:
    client = scope.get("client")
    if not client or client[0] not in LOOPBACK_HOSTS:
        return False
    forwarded = forwarded_for(scope)
    if not forwarded:
        return True
    return all(entry in LOOPBACK_HOSTS for entry in forwarded)


def forwarded_for(scope: Scope) -> list[str]:
    headers = dict(scope.get("headers", []))
    raw = headers.get(b"x-forwarded-for", b"").decode("latin-1")
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def check_basic_auth(
    authorization: str | None, expected: tuple[str, str]
) -> bool:
    if not authorization:
        return False
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() != "basic" or not credentials:
        return False
    try:
        decoded = base64.b64decode(credentials.strip()).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    username, _, password = decoded.partition(":")
    try:
        return secrets.compare_digest(
            username.encode("utf-8"), expected[0].encode("utf-8")
        ) and secrets.compare_digest(
            password.encode("utf-8"), expected[1].encode("utf-8")
        )
    except TypeError:
        return False


class BasicAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _credentials(scope: Scope) -> tuple[str, str] | None:
        app = scope.get("app")
        state_settings = getattr(app.state, "settings", None) if app is not None else None
        if isinstance(state_settings, Settings):
            return get_configured_credentials(state_settings)
        return get_configured_credentials()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        credentials = self._credentials(scope)
        if credentials is None:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api"):
            await self.app(scope, receive, send)
            return
        if is_loopback(scope):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        raw = headers.get(b"authorization", b"").decode("latin-1")
        if check_basic_auth(raw, credentials):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": "Authentication required"}, status_code=401
        )
        await response(scope, receive, send)
