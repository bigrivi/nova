"""Log every backend API error into the application log.

Failures used to be invisible in the places that matter. ``HTTPException``
(400/404/409, ...) is converted into a response by Starlette without a single
log line, and an unhandled exception becomes a bare 500 whose traceback only
reaches the ASGI server's stderr - which a packaged desktop app does not have.
So an endpoint like ``POST /api/agents/import`` could fail and leave nothing
in ``nova.log`` to say why.

Two handlers close that gap. They log first and then answer exactly the way
the defaults would, so the wire contract does not change: the ``Exception``
handler never sees an ``HTTPException`` because Starlette resolves handlers
along the exception's MRO and the more specific default wins.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


def install_error_logging(app: FastAPI) -> None:
    """Log API failures before answering them the default way.

    Args:
        app: The FastAPI application to instrument.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _log_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        log.warning(
            "API %s %s -> %s: %s",
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
        return await http_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def _log_unhandled_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # log.exception carries the traceback; the response stays generic so
        # internals never leak to the client.
        log.exception(
            "API %s %s -> 500: unhandled %s",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
