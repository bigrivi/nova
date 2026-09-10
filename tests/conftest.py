"""
Shared pytest fixtures
"""

import pytest


from nova.settings import get_settings
from nova.llm import OllamaProvider


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


@pytest.fixture
def llm():
    return OllamaProvider()
