"""The HTTP interface the refactor promised, pinned as data.

The refactor moved routers, split services and replaced the streaming path, so
the thing a client depends on has to be checked as an interface rather than as a
set of handler functions: which paths exist, which methods, which parameters,
which request body, and which response shape each one documents.

Two layers, on purpose:

* an explicit manifest below — a human reads it and can say "yes, that is the
  API" — so a removed or renamed route fails with a name, not a JSON diff;
* a normalised snapshot of the generated OpenAPI document, so a changed
  parameter, body or response shape fails too.

Regenerate the snapshot only when the interface is *meant* to change::

    NOVA_REGEN_OPENAPI=1 .venv/bin/pytest tests/test_api_contract.py
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from nova.server import create_app
from nova.settings import get_settings

CONTRACT_PATH = pathlib.Path(__file__).parent / "contracts" / "openapi_contract.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

#: Every route the server offers, in the shape a client addresses it.
ROUTES = {
    "GET /",
    "GET /health",
    # chat
    "POST /api/chat",
    "POST /api/chat/stream",
    "GET /api/chat/stream/status",
    "GET /api/chat/stream/active",
    "POST /api/chat/interrupt",
    "POST /api/chat/approve",
    "POST /api/sessions/{session_id}/regenerate",
    "GET /api/pending",
    # sessions
    "GET /api/sessions",
    "PATCH /api/sessions/{session_id}",
    "DELETE /api/sessions/{session_id}",
    "GET /api/sessions/{session_id}/messages",
    "GET /api/sessions/{session_id}/context",
    "POST /api/sessions/{session_id}/fork",
    "POST /api/sessions/{session_id}/compact",
    "GET /api/sessions/{session_id}/checkpoints",
    "POST /api/sessions/{session_id}/checkpoints/{checkpoint_id}/restore",
    "PUT /api/sessions/{session_id}/pinned",
    "PUT /api/sessions/{session_id}/project",
    "PUT /api/sessions/{session_id}/workspace",
    "GET /api/sessions/{session_id}/route",
    "PUT /api/sessions/{session_id}/route",
    "GET /api/sessions/{session_id}/pending",
    # projects
    "GET /api/projects",
    "POST /api/projects",
    "POST /api/projects/resolve",
    "PATCH /api/projects/{project_id}",
    "DELETE /api/projects/{project_id}",
    # agents and models
    "GET /api/agents",
    "POST /api/agents",
    "POST /api/agents/import",
    "GET /api/agents/{key}",
    "PATCH /api/agents/{key}",
    "DELETE /api/agents/{key}",
    "PUT /api/agents/{key}/parents",
    "GET /api/models",
    "GET /api/providers",
    "GET /api/providers/presets",
    "GET /api/providers/{key}/available-models",
    "POST /api/providers/sync-models",
    "POST /api/config/providers",
    "POST /api/config/providers/update",
    "POST /api/config/providers/delete",
    "POST /api/config/providers/{key}/sync-models",
    "POST /api/config/models",
    "POST /api/config/models/update",
    "POST /api/config/models/delete",
    "POST /api/config/mcp/add",
    "POST /api/config/mcp/update",
    "POST /api/config/mcp/delete",
    "POST /api/config/mcp/test",
    "POST /api/registry/refresh",
    # memories, permissions, git, filesystem
    "GET /api/memories",
    "DELETE /api/memories/{memory_id}",
    "GET /api/permissions",
    "GET /api/git/status",
    "GET /api/git/diff",
    "GET /api/git/commit-plan",
    "POST /api/git/commit",
    "POST /api/git/review",
    "GET /api/fs/list",
    # tasks, schedules, events, speech, mcp
    "GET /api/tasks",
    "GET /api/tasks/{task_id}",
    "GET /api/tasks/{task_id}/logs",
    "POST /api/tasks/{task_id}/cancel",
    "GET /api/schedules",
    "POST /api/schedules",
    "PATCH /api/schedules/{job_id}",
    "DELETE /api/schedules/{job_id}",
    "POST /api/schedules/{job_id}/run",
    "GET /api/events",
    "POST /api/speech/start",
    "POST /api/speech/stop",
    "POST /api/speech/cancel",
    "POST /api/speech/transcribe",
    "GET /api/speech/status",
    "GET /api/mcp-servers",
}


@pytest.fixture(scope="module")
def schema() -> dict:
    return create_app(settings=get_settings()).openapi()


def _operations(schema: dict) -> dict[str, dict]:
    operations = {}
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                operations[f"{method.upper()} {path}"] = operation
    return operations


def _project(schema: dict) -> dict:
    """A stable, reviewable projection of the generated document.

    Only what a client binds to: parameters, whether a body is accepted and with
    which media types, and the documented responses. Descriptions are left out so
    that wording changes are not interface changes.
    """
    projected = {}
    for key, operation in sorted(_operations(schema).items()):
        parameters = [
            [item["name"], item["in"], bool(item.get("required"))]
            for item in sorted(
                operation.get("parameters", []),
                key=lambda item: (item["name"], item["in"]),
            )
        ]
        body = operation.get("requestBody")
        media_types = sorted(body["content"]) if body else []
        responses = {}
        for status, response in operation.get("responses", {}).items():
            shapes = []
            for media, spec in (response.get("content") or {}).items():
                model = spec.get("schema", {})
                shapes.append([media, model.get("$ref") or model.get("type")])
            responses[status] = sorted(shapes)
        projected[key] = {
            "parameters": parameters,
            "request": media_types,
            "responses": responses,
        }
    return projected


def test_the_http_surface_is_what_the_manifest_says(schema):
    served = set(_operations(schema))

    missing = ROUTES - served
    extra = served - ROUTES

    assert not missing, f"documented routes the app does not serve: {sorted(missing)}"
    assert not extra, f"routes serving that the manifest does not document: {sorted(extra)}"


def test_parameters_bodies_and_responses_match_the_recorded_contract(schema):
    current = _project(schema)
    if os.environ.get("NOVA_REGEN_OPENAPI") == "1":
        CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT_PATH.write_text(
            json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        pytest.skip(f"contract regenerated at {CONTRACT_PATH}")

    assert CONTRACT_PATH.exists(), "missing contract snapshot; run with NOVA_REGEN_OPENAPI=1"
    expected = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    changed = {
        key: {"expected": expected.get(key), "actual": current.get(key)}
        for key in sorted(set(expected) | set(current))
        if expected.get(key) != current.get(key)
    }
    assert not changed, json.dumps(changed, indent=2)[:4000]


def test_the_chat_surface_keeps_its_wire_contract(schema):
    operations = _operations(schema)

    stream = operations["POST /api/chat/stream"]
    media = stream["responses"]["200"]["content"]
    assert "text/event-stream" in media, media

    aggregate = operations["POST /api/chat"]
    assert aggregate["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ChatResponse"), aggregate["responses"]["200"]

    for route in (
        "POST /api/chat/interrupt",
        "GET /api/chat/stream/status",
        "GET /api/sessions",
        "GET /api/sessions/{session_id}/messages",
    ):
        assert route in operations, route
