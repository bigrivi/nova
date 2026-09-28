"""API error logging: every failure leaves a record in the log.

Covers an unhandled exception (500, with traceback), a rejected request
(``HTTPException``, e.g. the 400/409 ``POST /api/agents/import`` can return),
and proof that a normal 200 stays silent.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from nova.server.error_logging import install_error_logging


@pytest.fixture
def client():
    app = FastAPI()
    install_error_logging(app)

    @app.get("/ok")
    async def ok() -> dict:
        return {"status": "ok"}

    @app.get("/boom")
    async def boom() -> dict:
        raise ValueError("something broke inside")

    @app.get("/reject")
    async def reject() -> dict:
        raise HTTPException(status_code=409, detail="Agent 'x' already exists")

    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_returns_generic_500_with_traceback_logged(
    client, caplog
):
    with caplog.at_level(logging.ERROR, logger="nova.server.error_logging"):
        response = client.get("/boom")

    assert response.status_code == 500
    # Generic on the wire: internals must not leak to the client.
    assert response.json() == {"detail": "Internal server error"}

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, [r.getMessage() for r in caplog.records]
    assert "GET /boom -> 500" in errors[0].getMessage()
    assert "ValueError" in errors[0].getMessage()
    assert errors[0].exc_info is not None
    assert errors[0].exc_info[0] is ValueError


def test_http_exception_keeps_its_response_and_is_logged_as_warning(
    client, caplog
):
    with caplog.at_level(logging.WARNING, logger="nova.server.error_logging"):
        response = client.get("/reject")

    # Untouched: the default handler still answers.
    assert response.status_code == 409
    assert response.json() == {"detail": "Agent 'x' already exists"}

    assert any(
        "GET /reject -> 409" in r.getMessage() for r in caplog.records
    ), [r.getMessage() for r in caplog.records]
    assert not any(
        r.levelno >= logging.ERROR for r in caplog.records
    ), "a client error must not log at error level"


def test_successful_requests_stay_silent(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="nova.server.error_logging"):
        response = client.get("/ok")

    assert response.status_code == 200
    assert caplog.records == []
