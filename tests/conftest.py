"""
Shared pytest fixtures
"""

from collections.abc import Mapping

import pytest

from nova.llm import OllamaProvider
from nova.settings import get_settings


@pytest.fixture(autouse=True)
def _test_settings_home(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / ".nova"))
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_session_manager():
    """Drop the process-global SessionManager between tests.

    Agent() falls back to get_session_manager(). Without a reset, a manager
    created in an earlier test keeps a data source whose connection the test
    fixture already closed; the next test reconnects it, leaking an aiosqlite
    worker thread that keeps pytest from exiting.
    """
    from nova.session import manager as session_manager_module

    previous = session_manager_module._manager
    session_manager_module._manager = None
    yield
    session_manager_module._manager = previous


@pytest.fixture(autouse=True)
def _reset_background_task_manager():
    """Drop the process-global BackgroundTaskManager between tests.

    The manager binds an asyncio.Semaphore to whichever loop first runs a
    task, and each pytest-asyncio test gets a fresh loop, so a singleton
    shared across tests can carry a semaphore bound to a closed loop. Same
    isolation rationale as _reset_session_manager above.
    """
    from nova.tasks import manager as task_manager_module

    previous = task_manager_module._manager
    task_manager_module._manager = None
    yield
    task_manager_module._manager = previous


@pytest.fixture
def make_executor():
    """Return a factory that wraps a coroutine function as a TaskExecutor.

    Lets a test register a one-off kind without writing a class:

        manager.register_executor(make_executor("example", run))
    """
    from nova.tasks.models import (
        TaskExecutionContext,
        TaskExecutionResult,
        TaskExecutor,
    )

    class _FunctionExecutor(TaskExecutor):
        def __init__(self, kind: str, run, *, unlimited: bool) -> None:
            self.kind = kind
            self.unlimited = unlimited
            self._run = run

        async def execute(
            self,
            arguments: Mapping[str, object],
            context: TaskExecutionContext,
        ) -> TaskExecutionResult:
            return await self._run(arguments, context)

    def _factory(
        kind: str, run, *, unlimited: bool = False
    ) -> TaskExecutor:
        return _FunctionExecutor(kind, run, unlimited=unlimited)

    return _factory


@pytest.fixture
def llm():
    return OllamaProvider()
