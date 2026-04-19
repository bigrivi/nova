"""
FastAPI server app for future frontend integration.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nova.settings import Settings, get_settings


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Nova API")
    app.state.settings = settings

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "nova",
            "mode": "server",
        }

    @app.get("/api/sessions")
    async def sessions() -> dict[str, Any]:
        return {
            "items": [],
            "status": "not_implemented",
        }

    @app.post("/api/chat")
    async def chat(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid JSON body."},
            )

        if not isinstance(payload, dict):
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid JSON body."},
            )

        return JSONResponse(
            status_code=501,
            content={
                "status": "not_implemented",
                "message": "Chat API is not implemented yet.",
                "request": payload,
            },
        )

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "nova",
            "mode": "server",
        }

    return app


async def run_server(settings: Optional[Settings] = None) -> None:
    app = create_app(settings=settings)
    host = app.state.settings.host
    port = app.state.settings.backend_port
    raise NotImplementedError(
        "Server mode requires an external ASGI runner. "
        f"FastAPI app is ready for {host}:{port}."
    )
