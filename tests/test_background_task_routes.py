from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova.server.routers.tasks import router
from nova.tasks.manager import BackgroundTaskManager


def _create_app(manager: BackgroundTaskManager) -> FastAPI:
    app = FastAPI()
    app.state.background_task_manager = manager
    app.include_router(router)
    return app


def test_task_routes_list_only_owned_session_tasks() -> None:
    """Task routes should require a session and return an empty owned list."""
    client = TestClient(_create_app(BackgroundTaskManager()))

    response = client.get("/api/tasks", params={"session_id": "session-a"})

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_task_routes_hide_unknown_or_unowned_tasks() -> None:
    """Unknown tasks should use the same 404 response as unowned tasks."""
    client = TestClient(_create_app(BackgroundTaskManager()))

    response = client.get(
        "/api/tasks/task-secret",
        params={"session_id": "session-a"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Background task not found"
