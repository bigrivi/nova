"""
Shared pytest fixtures
"""

import pytest

from nova.skills import reset_skill_service
from nova.settings import get_settings
from nova.llm import OllamaProvider


@pytest.fixture(autouse=True)
def _test_settings_home(monkeypatch, tmp_path):
    get_settings.cache_clear()
    reset_skill_service()
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / ".nova"))
    yield
    get_settings.cache_clear()
    reset_skill_service()


@pytest.fixture
def llm():
    return OllamaProvider()
