"""One construction point for the handles a server shares.

``create_app`` used to assemble seven handles onto ``app.state`` under seven
names, and each reader had to know which name to reach for. ``AppContext`` is
that assembly, typed, and ``deps`` resolves through it.

What this buys, and what it cannot: the streaming runtime (registry, buffer, chat
service, speech, event bus) is per app and therefore isolated between two apps in
one process. The background task manager, the session manager and the default
data source stay process-wide singletons on purpose -- the TUI and the server are
two fronts on the same running work -- so a second app still shares them, and
``tests/conftest.py`` keeps resetting them.
"""

from __future__ import annotations

import pytest

from nova.server import create_app
from nova.server.context import AppContext
from nova.settings import get_settings


@pytest.fixture
def two_apps(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    get_settings.cache_clear()
    return create_app(settings=get_settings()), create_app(settings=get_settings())


def test_create_app_publishes_one_context(two_apps):
    first, _ = two_apps

    context = first.state.context

    assert isinstance(context, AppContext)
    # The four handles a reload must not replace are all on the context.
    assert context.request_registry is not None
    assert context.stream_buffer is not None
    assert context.session_event_bus is not None
    assert context.settings is not None


def test_dependencies_resolve_through_the_context(two_apps):
    from types import SimpleNamespace

    from nova.server.deps import (
        context_of,
        get_chat_service,
        get_request_registry,
        get_settings,
    )

    first, _ = two_apps
    request = SimpleNamespace(app=first)

    assert context_of(request) is first.state.context
    assert get_chat_service(request) is first.state.context.chat_service
    assert get_request_registry(request) is first.state.context.request_registry
    assert get_settings(request) is first.state.context.settings


def test_two_apps_do_not_share_their_streaming_runtime(two_apps):
    first, second = two_apps
    left, right = first.state.context, second.state.context

    assert left.request_registry is not right.request_registry
    assert left.stream_buffer is not right.stream_buffer
    assert left.session_event_bus is not right.session_event_bus
    assert left.chat_service is not right.chat_service
    assert left.speech_service is not right.speech_service


@pytest.mark.asyncio
async def test_a_slot_in_one_app_is_unknown_to_the_other(two_apps):
    first, second = two_apps

    await first.state.context.request_registry.register("s1", object())

    assert await first.state.context.request_registry.slot_state("s1") == "active"
    assert await second.state.context.request_registry.slot_state("s1") is None
