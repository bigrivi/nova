import pytest
from prompt_toolkit.document import Document
import re

from nova.agent.core import AgentEvent
from nova.cli.commands import CommandDispatcher, CommandRegistry
from nova.cli.completion import CommandCompleter
from nova.cli.history_render import render_question_prompt
from nova.cli.repl import NovaCLI, parse_options
from nova.cli.session_manager import SessionManager
from nova.cli.terminal_display import TerminalDisplay
from nova.cli.ui import (
    INPUT_UI_REFRESH_INTERVAL,
    ModelGroup,
    ModelSelection,
    PromptToolkitInputUI,
    SessionSelection,
    _format_relative_time,
    _session_conversation_width,
)
from nova.cli.tool_rendering import render_tool_result
from nova.cli.utils import looks_like_error_message
from dataclasses import replace

from nova.db.database import Message
from nova.settings import ProviderConfig, Settings
from nova.llm.provider import ToolResult


class _FakeMonitor:
    def start(self):
        return None

    def stop(self):
        return None


class _FakeAgent:
    def __init__(self, events):
        self._events = events
        self.session = None
        self.interrupted = False

    async def chat_stream(self, user_input, session_id=None):
        for item in self._events:
            yield item

    def interrupt(self):
        self.interrupted = True


def _make_test_display(*, width: int = 20) -> TerminalDisplay:
    return TerminalDisplay(width_provider=lambda: width)


def _init_test_repl(repl: NovaCLI, *, width: int = 20) -> NovaCLI:
    repl._display = _make_test_display(width=width)
    repl._session_manager = SessionManager(
        agent=repl.agent,
        display=repl._display,
    )
    repl._exit_code = None
    return repl


def _make_test_session_manager(repl: NovaCLI) -> SessionManager:
    return SessionManager(agent=repl.agent, display=repl._display)


def test_novacli_builds_runtime_from_settings(monkeypatch):
    captured = {}

    def fake_build_agent(settings):
        captured["settings"] = settings
        return _FakeAgent([])

    monkeypatch.setattr(
        "nova.cli.repl.build_agent",
        fake_build_agent,
    )
    settings = replace(
        Settings.load_config(),
        provider="openai",
        model="gpt-4o",
        openai_base_url="http://openai.local/v1",
        openai_api_key="secret",
    )

    cli = NovaCLI(settings=settings)

    assert cli.settings.provider == "openai"
    assert cli.settings.model == "gpt-4o"
    assert cli.settings.openai_base_url == "http://openai.local/v1"
    assert cli.settings.openai_api_key == "secret"
    assert captured["settings"] == cli.settings


def test_novacli_current_model_label_resolves_configured_model_alias():
    base_settings = Settings.load_config()
    settings = replace(
        base_settings,
        provider="openai",
        model="gpt-5.4",
        providers={
            "openai": ProviderConfig(
                type="openai-compatible",
                name="OpenAI Compatible",
                options={"base_url": "http://openai.local/v1", "api_key": "secret"},
                models={"gpt-5.4": {"name": "gpt-5.4-mini"}},
            )
        },
        provider_type="openai-compatible",
        openai_base_url="http://openai.local/v1",
        openai_api_key="secret",
    )
    repl = NovaCLI.__new__(NovaCLI)
    repl.settings = settings

    assert repl._current_model_label() == "gpt-5.4-mini"


def test_novacli_rebuild_runtime_updates_agent_and_session_manager(monkeypatch):
    built_agents: list[object] = []

    def fake_build_agent(settings):
        agent = _FakeAgent([])
        built_agents.append((settings, agent))
        return agent

    monkeypatch.setattr("nova.cli.repl.build_agent", fake_build_agent)

    settings = replace(Settings.load_config(), model="gemma4:26b")
    cli = NovaCLI(settings=settings)
    original_agent = cli.agent

    cli._rebuild_runtime(provider="openai", model="gpt-5.4")

    assert cli.settings.provider == "openai"
    assert cli.settings.model == "gpt-5.4"
    assert cli.agent is built_agents[-1][1]
    assert cli.agent is not original_agent
    assert cli._session_manager._agent is cli.agent


def test_novacli_find_model_provider_returns_matching_provider():
    settings = replace(
        Settings.load_config(),
        providers={
            "ollama": ProviderConfig(
                type="ollama",
                name="Ollama",
                options={"base_url": "http://localhost:11434"},
                models={"gemma4:26b": {"name": "gemma4:26b"}},
            ),
            "openai": ProviderConfig(
                type="openai-compatible",
                name="OpenAI Compatible",
                options={"base_url": "http://openai.local/v1", "api_key": "secret"},
                models={"gpt-5.4": {"name": "gpt-5.4"}},
            ),
        },
    )
def test_prompt_toolkit_input_ui_builds_model_fragments():
    ui = PromptToolkitInputUI(model_label="gpt-5.4")

    assert ui._build_model_fragments() == [("class:model-info", "  gpt-5.4")]


def test_prompt_toolkit_input_ui_uses_dynamic_model_label_provider():
    current_model = {"value": "gpt-5.4"}
    ui = PromptToolkitInputUI(
        model_label_provider=lambda: current_model["value"],
    )

    assert ui._build_model_fragments() == [("class:model-info", "  gpt-5.4")]

    current_model["value"] = "gemma4:26b"

    assert ui._build_model_fragments() == [("class:model-info", "  gemma4:26b")]


@pytest.mark.asyncio
async def test_prompt_toolkit_input_ui_prompt_model_selection_enables_periodic_refresh(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeApplication:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        async def run_async(self):
            return None

    monkeypatch.setattr("nova.cli.ui.Application", _FakeApplication)

    ui = PromptToolkitInputUI(model_label_provider=lambda: "gpt-5.4")
    result = await ui.prompt_model_selection(
        [ModelGroup(provider="openai", models=["gpt-5.4"])],
        current_provider="openai",
        current_model="gpt-5.4",
    )

    assert result is None
    assert captured["refresh_interval"] == INPUT_UI_REFRESH_INTERVAL
    assert captured["erase_when_done"] is True


@pytest.mark.asyncio
async def test_prompt_toolkit_input_ui_prompt_session_selection_enables_periodic_refresh(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeApplication:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        async def run_async(self):
            return None

    monkeypatch.setattr("nova.cli.ui.Application", _FakeApplication)

    ui = PromptToolkitInputUI(model_label_provider=lambda: "gpt-5.4")
    result = await ui.prompt_session_selection(
        [{"id": "sess-1", "title": "Greeting", "updated_at": 1714118400000}],
        current_session_id="sess-1",
    )

    assert result is None
    assert captured["refresh_interval"] == INPUT_UI_REFRESH_INTERVAL
    assert captured["erase_when_done"] is True


@pytest.mark.asyncio
async def test_prompt_toolkit_input_ui_prompt_model_selection_keeps_last_model_visible(monkeypatch):
    captured_render = {"text": ""}

    class _FakeApplication:
        def __init__(self, *args, **kwargs):
            def _find_control(container):
                if hasattr(container, "content") and hasattr(container.content, "text"):
                    return container.content
                if hasattr(container, "body"):
                    control = _find_control(container.body)
                    if control is not None:
                        return control
                for child in getattr(container, "children", []):
                    control = _find_control(child)
                    if control is not None:
                        return control
                return None

            layout = kwargs["layout"]
            control = _find_control(layout.container)
            assert control is not None
            fragments = control.text()
            captured_render["text"] = "".join(part for _, part in fragments)

        async def run_async(self):
            return None

    monkeypatch.setattr("nova.cli.ui.Application", _FakeApplication)

    ui = PromptToolkitInputUI()
    await ui.prompt_model_selection(
        [
            ModelGroup(provider="ollama", models=["gemma4:26b"]),
            ModelGroup(provider="openai", models=["gpt-5.4"]),
        ],
        current_provider="ollama",
        current_model="gemma4:26b",
    )

    assert "└─ openai" in captured_render["text"]
    assert "   • gpt-5.4" in captured_render["text"]


@pytest.mark.asyncio
async def test_prompt_toolkit_input_ui_prompt_session_selection_renders_current_marker(monkeypatch):
    captured_render = {"text": "", "fragments": []}

    class _FakeApplication:
        def __init__(self, *args, **kwargs):
            def _find_control(container):
                if hasattr(container, "content") and hasattr(container.content, "text"):
                    return container.content
                if hasattr(container, "body"):
                    control = _find_control(container.body)
                    if control is not None:
                        return control
                for child in getattr(container, "children", []):
                    control = _find_control(child)
                    if control is not None:
                        return control
                return None

            layout = kwargs["layout"]
            control = _find_control(layout.container)
            assert control is not None
            fragments = control.text()
            captured_render["fragments"] = fragments
            captured_render["text"] = "".join(part for _, part in fragments)

        async def run_async(self):
            return None

    monkeypatch.setattr("nova.cli.ui.Application", _FakeApplication)

    ui = PromptToolkitInputUI()
    await ui.prompt_session_selection(
        [
            {"id": "sess-1", "title": "Greeting", "created_at": 1714114800000, "updated_at": 1714118400000},
            {"id": "sess-2", "title": "Follow up", "created_at": 1714118400000, "updated_at": 1714122000000},
        ],
        current_session_id="sess-2",
    )

    assert "Select a session" in captured_render["text"]
    assert "Created" in captured_render["text"]
    assert "Updated" in captured_render["text"]
    assert "Conversation" in captured_render["text"]
    assert "Follow up" in captured_render["text"]
    assert "›" in captured_render["text"]
    assert ("class:selector-current-session", "•") in captured_render["fragments"]


@pytest.mark.asyncio
async def test_prompt_toolkit_input_ui_prompt_session_selection_uses_windowed_rendering(monkeypatch):
    captured_render = {"text": ""}

    class _FakeApplication:
        def __init__(self, *args, **kwargs):
            def _find_control(container):
                if hasattr(container, "content") and hasattr(container.content, "text"):
                    return container.content
                if hasattr(container, "body"):
                    control = _find_control(container.body)
                    if control is not None:
                        return control
                for child in getattr(container, "children", []):
                    control = _find_control(child)
                    if control is not None:
                        return control
                return None

            layout = kwargs["layout"]
            control = _find_control(layout.container)
            assert control is not None
            fragments = control.text()
            captured_render["text"] = "".join(part for _, part in fragments)

        async def run_async(self):
            return None

    monkeypatch.setattr("nova.cli.ui.Application", _FakeApplication)

    sessions = [
        {
            "id": f"sess-{idx}",
            "title": f"Session {idx}",
            "created_at": 1714114800000 + idx * 1000,
            "updated_at": 1714118400000 + idx * 1000,
        }
        for idx in range(1, 12)
    ]
    ui = PromptToolkitInputUI()
    await ui.prompt_session_selection(
        sessions,
        current_session_id="sess-11",
    )

    assert "↑ 3 earlier sessions" in captured_render["text"]
    assert "↓" not in captured_render["text"]
    assert "Session 11" in captured_render["text"]
    assert "›" in captured_render["text"]
    assert "Session 2                        " not in captured_render["text"]


def test_format_relative_time_uses_friendly_labels():
    assert _format_relative_time(0) == "unknown"
    assert _format_relative_time(1714118400000, now_ts=1714118405) == "just now"
    assert _format_relative_time(1714118400000, now_ts=1714118460) == "1 minute ago"
    assert _format_relative_time(1714118400000, now_ts=1714118520) == "2 minutes ago"
    assert _format_relative_time(1714118400000, now_ts=1714122000) == "1 hour ago"
    assert _format_relative_time(1714118400000, now_ts=1714204800) == "1 day ago"
    assert _format_relative_time(1714118400000, now_ts=1714291200) == "2 days ago"


def test_session_conversation_width_adapts_to_terminal_columns():
    assert _session_conversation_width(80) >= 24
    assert _session_conversation_width(120) > _session_conversation_width(80)


@pytest.mark.asyncio
async def test_prompt_toolkit_input_ui_prompt_session_selection_keeps_current_label_visible_for_long_titles(monkeypatch):
    captured_render = {"text": "", "fragments": []}

    class _FakeApplication:
        def __init__(self, *args, **kwargs):
            def _find_control(container):
                if hasattr(container, "content") and hasattr(container.content, "text"):
                    return container.content
                if hasattr(container, "body"):
                    control = _find_control(container.body)
                    if control is not None:
                        return control
                for child in getattr(container, "children", []):
                    control = _find_control(child)
                    if control is not None:
                        return control
                return None

            layout = kwargs["layout"]
            control = _find_control(layout.container)
            assert control is not None
            fragments = control.text()
            captured_render["fragments"] = fragments
            captured_render["text"] = "".join(part for _, part in fragments)

        async def run_async(self):
            return None

    monkeypatch.setattr("nova.cli.ui.Application", _FakeApplication)
    monkeypatch.setattr("nova.cli.ui._session_conversation_width", lambda terminal_columns=None: 24)

    ui = PromptToolkitInputUI()
    await ui.prompt_session_selection(
        [
            {
                "id": "sess-1",
                "title": "This is a very long conversation title that should be truncated safely",
                "created_at": 1714114800000,
                "updated_at": 1714118400000,
            }
        ],
        current_session_id="sess-1",
    )

    assert "›" in captured_render["text"]
    assert ("class:selector-current-session", " ") in captured_render["fragments"] or ("class:selector-current-session", "•") in captured_render["fragments"]


@pytest.mark.asyncio
async def test_prompt_toolkit_input_ui_enables_periodic_refresh(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeApplication:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        async def run_async(self):
            return None

    monkeypatch.setattr("nova.cli.ui.Application", _FakeApplication)

    ui = PromptToolkitInputUI(model_label_provider=lambda: "gpt-5.4")
    result = await ui.prompt("❯ ")

    assert result == ""
    assert captured["refresh_interval"] == INPUT_UI_REFRESH_INTERVAL
    assert captured["erase_when_done"] is True


@pytest.mark.asyncio
async def test_models_command_uses_selector_and_switches_runtime(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl.settings = replace(
        Settings.load_config(),
        provider="openai",
        model="gpt-5.4",
        providers={
            "ollama": ProviderConfig(
                type="ollama",
                name="Ollama",
                options={"base_url": "http://localhost:11434"},
                models={"gemma4:26b": {"name": "gemma4:26b"}},
            ),
            "openai": ProviderConfig(
                type="openai-compatible",
                name="OpenAI Compatible",
                options={"base_url": "http://openai.local/v1", "api_key": "secret"},
                models={
                    "gpt-5.4": {"name": "gpt-5.4"},
                    "gpt-5.4-mini": {"name": "gpt-5.4-mini"},
                },
            ),
        },
    )
    repl._display = _make_test_display()
    repl._input_ui = PromptToolkitInputUI()
    repl._session_manager = SessionManager(agent=repl.agent, display=repl._display)

    captured_groups: dict[str, object] = {}
    messages: list[str] = []
    called: dict[str, str] = {}

    async def fake_prompt_model_selection(groups, *, current_provider, current_model):
        captured_groups["groups"] = groups
        captured_groups["current_provider"] = current_provider
        captured_groups["current_model"] = current_model
        return ModelSelection(provider="ollama", model="gemma4:26b")

    def fake_rebuild_runtime(*, provider: str | None = None, model: str | None = None) -> None:
        called["provider"] = provider or ""
        called["model"] = model or ""
        repl.settings = replace(
            repl.settings,
            provider=provider or repl.settings.provider,
            model=model or repl.settings.model,
        )

    monkeypatch.setattr(repl._input_ui, "prompt_model_selection", fake_prompt_model_selection)
    monkeypatch.setattr(repl, "_rebuild_runtime", fake_rebuild_runtime)
    monkeypatch.setattr(repl._display, "info", lambda text: messages.append(text))

    handled = await repl._handle_models_command(type("Cmd", (), {"args": ""})())

    assert handled is True
    assert captured_groups == {
        "groups": [
            ModelGroup(provider="ollama", models=["gemma4:26b"]),
            ModelGroup(provider="openai", models=["gpt-5.4", "gpt-5.4-mini"]),
        ],
        "current_provider": "openai",
        "current_model": "gpt-5.4",
    }
    assert called == {"provider": "ollama", "model": "gemma4:26b"}
    assert messages == [
        "Model switched to: gemma4:26b",
    ]


@pytest.mark.asyncio
async def test_models_command_handles_empty_model_list(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl.settings = replace(
        Settings.load_config(),
        provider="openai",
        model="",
        providers={
            "ollama": ProviderConfig(
                type="ollama",
                name="Ollama",
                options={"base_url": "http://localhost:11434"},
                models={},
            ),
            "openai": ProviderConfig(
                type="openai-compatible",
                name="OpenAI Compatible",
                options={"base_url": "http://openai.local/v1", "api_key": "secret"},
                models={},
            ),
        },
    )
    repl._display = _make_test_display()
    repl._input_ui = PromptToolkitInputUI()
    repl._session_manager = SessionManager(agent=repl.agent, display=repl._display)

    messages: list[str] = []
    monkeypatch.setattr(repl._display, "info", lambda text: messages.append(text))

    handled = await repl._handle_models_command(type("Cmd", (), {"args": ""})())

    assert handled is True
    assert messages == [
        "Configured models:",
        "\033[1m├─ ollama\033[0m",
        "│  No configured models",
        "\033[1m└─ openai\033[0m",
        "   No configured models",
    ]


@pytest.mark.asyncio
async def test_models_command_handles_selector_cancel(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl.settings = replace(
        Settings.load_config(),
        provider="openai",
        model="gpt-5.4",
        providers={
            "openai": ProviderConfig(
                type="openai-compatible",
                name="OpenAI Compatible",
                options={"base_url": "http://openai.local/v1", "api_key": "secret"},
                models={"gpt-5.4": {"name": "gpt-5.4"}},
            ),
        },
    )
    repl._display = _make_test_display()
    repl._input_ui = PromptToolkitInputUI()
    repl._session_manager = SessionManager(agent=repl.agent, display=repl._display)

    async def fake_prompt_model_selection(*args, **kwargs):
        return None

    monkeypatch.setattr(repl._input_ui, "prompt_model_selection", fake_prompt_model_selection)
    monkeypatch.setattr(repl._display, "info", lambda text: (_ for _ in ()).throw(AssertionError(text)))

    handled = await repl._handle_models_command(type("Cmd", (), {"args": ""})())

    assert handled is True


@pytest.mark.asyncio
async def test_sessions_command_uses_selector_and_loads_session(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl.settings = Settings.load_config()
    repl._display = _make_test_display()
    repl._input_ui = PromptToolkitInputUI()
    repl._session_manager = SessionManager(agent=repl.agent, display=repl._display)

    async def fake_list_sessions():
        return [
            {"id": "sess-1", "title": "Greeting", "updated_at": 1714118400000},
            {"id": "sess-2", "title": "Follow up", "updated_at": 1714122000000},
        ]

    async def fake_prompt_session_selection(sessions, *, current_session_id):
        assert current_session_id is None
        assert len(sessions) == 2
        return SessionSelection(session_id="sess-2")

    loaded: list[str] = []

    async def fake_load_session_by_id(session_id: str):
        loaded.append(session_id)

    monkeypatch.setattr(repl._session_manager, "list_sessions", fake_list_sessions)
    monkeypatch.setattr(repl._input_ui, "prompt_session_selection", fake_prompt_session_selection)
    monkeypatch.setattr(repl._session_manager, "load_session_by_id", fake_load_session_by_id)

    handled = await repl._handle_sessions_command(type("Cmd", (), {"args": ""})())

    assert handled is True
    assert loaded == ["sess-2"]


def test_looks_like_error_message():
    assert looks_like_error_message("Error: HTTP 400 from provider")
    assert looks_like_error_message(" error: bad request ")
    assert not looks_like_error_message("")
    assert not looks_like_error_message("Hello world")


def test_render_tool_result_formats_edit_diff():
    rendered = render_tool_result(
        "edit",
        "Changes applied to foo.py:\n\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n",
    )

    assert rendered is not None
    assert "\033[1;35m[EDIT DIFF]\033[0m Changes applied to foo.py:" in rendered
    assert "\033[1;36m--- a/foo.py\033[0m" in rendered
    assert "\033[1;36m+++ b/foo.py\033[0m" in rendered
    assert "\033[31m-old\033[0m" in rendered
    assert "\033[32m+new\033[0m" in rendered


def test_render_tool_result_ignores_other_tools():
    rendered = render_tool_result("bash", "stdout here")
    assert rendered is not None
    assert "stdout here" in rendered


def test_render_history_message_formats_user_visible_roles():
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    rendered_width = 20
    clean_len = lambda s: len(ansi_re.sub("", s))
    display = _make_test_display(width=rendered_width)

    rendered_user = display.render_history_message("user", " Hello ")
    assert rendered_user is not None
    assert "❯ " in rendered_user
    assert "Hello" in rendered_user
    assert "\033[" in rendered_user
    assert rendered_user.endswith("\033[0m")
    user_lines = rendered_user.splitlines()
    assert len(user_lines) == 3
    assert clean_len(user_lines[0]) == rendered_width
    assert "❯ Hello" in ansi_re.sub("", user_lines[1])
    assert clean_len(user_lines[1]) == rendered_width
    assert clean_len(user_lines[2]) == rendered_width
    assert display.render_history_message("assistant", "Hi there") == "• Hi there"
    rendered_multiline = display.render_history_message("user", "line 1\nline 2")
    assert rendered_multiline is not None
    assert "line 1" in rendered_multiline
    assert "line 2" in rendered_multiline
    assert len(rendered_multiline.splitlines()) == 4
    assert all(clean_len(line) == rendered_width for line in rendered_multiline.splitlines())
    multiline_lines = rendered_multiline.splitlines()
    assert "  line 2" in ansi_re.sub("", multiline_lines[2])
    assert display.render_history_message("assistant", "line 1\nline 2") == "• line 1\n  line 2"
    assert display.render_history_message("tool", "ignored") == "Tool: ignored"
    assert display.render_history_message("user", "   ") is None


def test_print_history_transcript_uses_chat_like_spacing(monkeypatch):
    captured = []
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    display = _make_test_display(width=20)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: captured.append(" ".join(str(arg) for arg in args)))

    display.print_history_transcript(
        [
            Message(id="m1", session_id="sess-1", role="user", content="hello"),
            Message(id="m2", session_id="sess-1", role="assistant", content="hi"),
        ]
    )

    assert len(captured) == 5
    assert captured[0] == ""
    block_lines = captured[1].splitlines()
    assert len(block_lines) == 3
    assert "❯ hello" in ansi_re.sub("", block_lines[1])
    assert all(len(ansi_re.sub("", line)) == 20 for line in block_lines)
    assert captured[2] == ""
    assert captured[3] == "• hi"
    assert captured[4] == ""


def test_print_history_transcript_shows_ask_user_and_edit_diff(monkeypatch):
    captured = []
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    display = _make_test_display(width=20)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: captured.append(" ".join(str(arg) for arg in args)))

    display.print_history_transcript(
        [
            Message(id="m1", session_id="sess-1", role="assistant", content="", tool_calls=[{"id": "call_1", "name": "ask_user"}]),
            Message(
                id="m2",
                session_id="sess-1",
                role="tool",
                tool_call_id="call_1",
                content='{"question":{"header":"Current City","question":"Please choose a city","input_type":"select","options":[]}}',
            ),
            Message(id="m3", session_id="sess-1", role="assistant", content="", tool_calls=[{"id": "call_2", "name": "edit"}]),
            Message(
                id="m4",
                session_id="sess-1",
                role="tool",
                tool_call_id="call_2",
                content="Changes applied to foo.py:\n\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n",
            ),
            Message(id="m5", session_id="sess-1", role="assistant", content="Done"),
            Message(id="m6", session_id="sess-1", role="assistant", content="", tool_calls=[{"id": "call_3", "name": "bash"}]),
            Message(id="m7", session_id="sess-1", role="tool", tool_call_id="call_3", content="/tmp"),
        ]
    )

    output = "\n".join(captured)
    clean_output = ansi_re.sub("", output)
    assert "  ? Current City\n  Please choose a city" in clean_output
    assert "[EDIT DIFF]" in output
    assert "--- a/foo.py" in output
    assert "• Done" in output
    assert "└ /tmp" in clean_output


def test_print_user_message_renders_user_transcript(monkeypatch):
    display = _make_test_display(width=20)
    captured: list[str] = []
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: captured.append(" ".join(str(arg) for arg in args)))

    display.print_user_message("hello")

    assert captured[0] == ""
    assert "❯ hello" in ansi_re.sub("", captured[1])
    assert captured[2] == ""


def test_stream_assistant_text_adds_prefix_only_once(monkeypatch):
    captured: list[str] = []
    display = _make_test_display()
    monkeypatch.setattr(display, "_stream_text", lambda text: captured.append(text))

    display.reset()
    display.write_text_chunk("Hello", is_first=True)
    display.write_text_chunk(" world", is_first=False)

    assert captured == ["• Hello", " world"]


def test_render_assistant_message_indents_continuation_lines():
    display = _make_test_display()
    assert display.render_assistant_message("line 1\nline 2\nline 3") == "• line 1\n  line 2\n  line 3"


def test_render_assistant_message_wraps_long_lines(monkeypatch):
    display = _make_test_display(width=10)
    assert display.render_assistant_message("abcdefghijk") == "• abcdefghij\n  k"


def test_stream_assistant_text_indents_multiline_followups(monkeypatch):
    captured: list[str] = []
    display = _make_test_display()
    monkeypatch.setattr(display, "_stream_text", lambda text: captured.append(text))

    display.reset()
    display.write_text_chunk("line 1\nline", is_first=True)
    display.write_text_chunk(" 2\nline 3", is_first=False)

    assert captured == ["• line 1\n  line", " 2\n  line 3"]


def test_stream_assistant_text_wraps_auto_lines(monkeypatch):
    captured: list[str] = []
    display = _make_test_display(width=10)
    monkeypatch.setattr(display, "_stream_text", lambda text: captured.append(text))

    display.reset()
    display.write_text_chunk("abcdefgh", is_first=True)
    display.write_text_chunk("ijk", is_first=False)

    assert captured == ["• abcdefgh", "ij\n  k"]


def test_render_tool_result_truncates_long_diff():
    diff_lines = ["--- a/foo.py", "+++ b/foo.py", "@@ -1 +1 @@"]
    diff_lines.extend(f"+line {i}" for i in range(100))
    rendered = render_tool_result(
        "write",
        "File updated - foo.py:\n\n" + "\n".join(diff_lines) + "\n",
    )

    assert rendered is not None
    assert "\033[1;35m[WRITE DIFF]\033[0m File updated - foo.py:" in rendered
    assert "... (23 more diff lines not shown)" in rendered


def test_print_tool_result_skips_ask_user_payload(monkeypatch):
    display = _make_test_display()
    captured: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: captured.append(" ".join(str(arg) for arg in args)))

    display.print_tool_result(
        "ask_user",
        '{"question":{"header":"需要位置信息","question":"请告诉我城市","input_type":"text","options":[]}}',
    )

    assert captured == []


def test_print_tool_call_simplifies_ask_user(monkeypatch):
    display = _make_test_display()
    captured: list[str] = []
    tool_call = type(
        "ToolCallStub",
        (),
        {
            "name": "ask_user",
            "arguments": '{"question":{"header":"需要位置信息","question":"请告诉我城市","input_type":"text","options":[]}}',
        },
    )()
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: captured.append(" ".join(str(arg) for arg in args)))

    display.print_tool_call(tool_call, "ask_user")

    assert len(captured) == 1
    assert "Asking for user input" in captured[0]
    assert "需要位置信息" not in captured[0]
    assert '"question"' not in captured[0]


@pytest.mark.asyncio
async def test_run_shows_cli_banner_with_slash_commands(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    _init_test_repl(repl)
    repl._command_registry = CommandRegistry()
    repl._command_dispatcher = CommandDispatcher(
        registry=repl._command_registry,
        handlers={},
    )
    repl._pending_input = None
    repl._streaming = False
    repl._stop_requested = False
    repl._running = False
    repl._input_ui = None

    captured = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: captured.append(" ".join(str(arg) for arg in args)))

    async def fake_prompt():
        raise EOFError

    repl._prompt_chat = fake_prompt

    await repl.run()

    assert "Nova CLI" in captured
    assert "Type 'exit' or 'quit' to leave." in captured
    assert "Use /new, /sessions, /clear, /models, or /quit for commands." in captured


@pytest.mark.asyncio
async def test_run_closes_session_manager_on_exit(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    _init_test_repl(repl)
    repl._command_registry = CommandRegistry()
    repl._command_dispatcher = CommandDispatcher(
        registry=repl._command_registry,
        handlers={},
    )
    repl._pending_input = None
    repl._streaming = False
    repl._stop_requested = False
    repl._running = False
    repl._input_ui = None

    closed = {"called": False}

    async def fake_close_session_manager():
        closed["called"] = True

    monkeypatch.setattr("nova.cli.repl.close_session_manager", fake_close_session_manager)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    async def fake_prompt():
        raise EOFError

    repl._prompt_chat = fake_prompt

    await repl.run()

    assert closed["called"] is True


@pytest.mark.asyncio
async def test_clear_command_redraws_banner(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    _init_test_repl(repl)
    repl._command_registry = CommandRegistry()

    captured = []
    monkeypatch.setattr(repl._display, "clear_terminal", lambda: captured.append("__cleared__"))
    monkeypatch.setattr(
        "builtins.print",
        lambda *args, **kwargs: captured.append(" ".join(str(arg) for arg in args)),
    )

    handled = await repl._handle_clear_command(None)

    assert handled is True
    assert captured[0] == "__cleared__"
    assert "Nova CLI" in captured
    assert "Type 'exit' or 'quit' to leave." in captured
    assert "Use /new, /sessions, /clear, /models, or /quit for commands." in captured


def test_parse_options_requires_json_payload():
    content = """## Questions

**1. Current City**
Please enter your city

Please enter the city name directly, for example:

- Beijing
- Shanghai
- Shenzhen
"""

    assert parse_options(content) == []


def test_render_question_prompt_omits_header_line_when_header_missing():
    rendered = render_question_prompt(
        {
            "header": "",
            "question": "Please tell me which city you want the weather for.",
            "input_type": "text",
            "options": [],
        }
    )

    clean_rendered = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
    assert clean_rendered == "  Please tell me which city you want the weather for."


def test_command_registry_parses_slash_and_bare_commands():
    registry = CommandRegistry()

    parsed_slash = registry.parse("/sessions")
    assert parsed_slash is not None
    assert parsed_slash.spec.id == "sessions"
    assert parsed_slash.args == ""

    parsed_bare = registry.parse("q")
    assert parsed_bare is not None
    assert parsed_bare.spec.id == "quit"

    assert registry.parse("hello nova") is None


def test_clear_terminal_resets_screen(monkeypatch):
    written: list[str] = []
    flushed = {"called": False}
    display = _make_test_display()

    monkeypatch.setattr(display.spinner, "stop", lambda: None)
    monkeypatch.setattr(display, "flush", lambda: None)
    monkeypatch.setattr(
        "nova.cli.terminal_display.sys.stdout.write",
        lambda text: written.append(text),
    )
    monkeypatch.setattr(
        "nova.cli.terminal_display.sys.stdout.flush",
        lambda: flushed.__setitem__("called", True),
    )

    display.clear_terminal()

    assert written == ["\033[2J\033[H\033[3J"]
    assert flushed["called"] is True


def test_command_completer_suggests_new_for_n_prefix():
    completer = CommandCompleter(CommandRegistry())
    completions = list(completer.get_completions(Document("n", cursor_position=1), None))

    assert completions
    assert completions[0].display_text == "new"
    assert completions[0].text == "/new"


def test_command_completer_suggests_slash_command_for_slash_prefix():
    completer = CommandCompleter(CommandRegistry())
    completions = list(completer.get_completions(Document("/se", cursor_position=3), None))

    assert completions
    assert completions[0].display_text == "sessions"
    assert completions[0].text == "/sessions"


@pytest.mark.asyncio
async def test_load_session_by_id_reads_history_messages_from_db(monkeypatch):
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    class _FakeSessionManager:
        async def load_session(self, session_id):
            return {"id": session_id}

    class _FakeDb:
        async def get_messages(self, session_id, msg_filter=None):
            assert session_id == "sess-1"
            return [
                Message(id="m1", session_id=session_id, role="user", content="hello"),
                Message(id="m2", session_id=session_id, role="assistant", content="hi"),
            ]

    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl.agent.session = _FakeSessionManager()
    _init_test_repl(repl)

    captured = []
    repl._session_manager = _make_test_session_manager(repl)
    monkeypatch.setattr(repl._display, "info", lambda text: captured.append(text))
    monkeypatch.setattr(repl._display, "error", lambda text: captured.append(f"ERROR::{text}"))
    repl._session_manager.set_cached_sessions_for_tests([{"id": "sess-1", "title": "Greeting"}])
    printed = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: printed.append(" ".join(str(arg) for arg in args)))

    async def fake_ensure_db():
        return _FakeDb()

    monkeypatch.setattr("nova.db.database.ensure_db", fake_ensure_db)

    await repl._session_manager.load_session_by_id("sess-1")

    assert repl._session_manager.current_id == "sess-1"
    assert captured == [
        "Loaded session: Greeting",
    ]
    assert len(printed) == 5
    assert printed[0] == ""
    block_lines = printed[1].splitlines()
    assert len(block_lines) == 3
    assert "❯ hello" in ansi_re.sub("", block_lines[1])
    assert all(len(ansi_re.sub("", line)) == 20 for line in block_lines)
    assert printed[2] == ""
    assert printed[3] == "• hi"
    assert printed[4] == ""


@pytest.mark.asyncio
async def test_load_session_by_id_reports_missing_history(monkeypatch):
    class _FakeSessionManager:
        async def load_session(self, session_id):
            return {"id": session_id}

    class _FakeDb:
        async def get_messages(self, session_id, msg_filter=None):
            return []

    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl.agent.session = _FakeSessionManager()
    _init_test_repl(repl)

    captured = []
    repl._session_manager = _make_test_session_manager(repl)
    monkeypatch.setattr(repl._display, "info", lambda text: captured.append(text))
    monkeypatch.setattr(repl._display, "error", lambda text: captured.append(f"ERROR::{text}"))
    repl._session_manager.set_cached_sessions_for_tests([{"id": "sess-2", "title": "Empty"}])

    async def fake_ensure_db():
        return _FakeDb()

    monkeypatch.setattr("nova.db.database.ensure_db", fake_ensure_db)

    await repl._session_manager.load_session_by_id("sess-2")

    assert captured == [
        "Loaded session: Empty",
        "No messages found",
    ]


def test_parse_options_parses_explicit_options_block():
    content = """{"question":{"header":"Current City","question":"Please choose a city","input_type":"select","options":[{"label":"Beijing","description":"Capital"},{"label":"Shanghai","description":"Municipality"}]}}"""

    options = parse_options(content)

    assert len(options) == 2
    assert options[0].label == "Beijing"
    assert options[0].description == "Capital"


def test_parse_options_requires_explicit_select_input_type():
    content = """{"question":{"header":"Current City","question":"Please tell me which city you want the weather for, such as Beijing or Shanghai.","input_type":"text","options":[{"label":"Enter city","description":"Tell me the city you are currently in"}]}}"""

    assert parse_options(content) == []


def test_parse_options_respects_input_type_text():
    content = """{"question":{"header":"Current City","question":"Please tell me which city you want the weather for, such as Beijing or Shanghai.","input_type":"text","options":[{"label":"Beijing","description":"Capital"},{"label":"Shanghai","description":"Municipality"}]}}"""

    assert parse_options(content) == []


@pytest.mark.asyncio
async def test_run_stream_shows_provider_error(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([(AgentEvent.DONE, "Error: HTTP 400 from provider: bad request")])
    _init_test_repl(repl)
    repl._pending_input = None
    repl._streaming = False
    repl._stop_requested = False
    repl._input_ui = None
    repl.create_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    monkeypatch.setattr(repl._display, "info", lambda text: captured.append(text))
    monkeypatch.setattr(repl._display, "error", lambda text: captured.append(f"ERROR::{text}"))

    monkeypatch.setattr(repl._display.spinner, "stop", lambda: None)
    monkeypatch.setattr(repl._display, "flush", lambda: None)
    monkeypatch.setattr(repl._display.spinner, "start_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(repl._display.spinner, "start_tool", lambda *args, **kwargs: None)

    await repl.run_stream("hi")

    assert captured == ["ERROR::Error: HTTP 400 from provider: bad request"]


@pytest.mark.asyncio
async def test_run_stream_does_not_repeat_assistant_message_after_streaming(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent(
        [
            (AgentEvent.TOOL_CALL, type("ToolCallStub", (), {"name": "bash", "arguments": '{"command":"pwd"}'})()),
            (AgentEvent.TEXT_DELTA, "Current path:\n\n`/Users/andy/Workspace/codes/ai/nova`"),
            (AgentEvent.DONE, "Current path:\n\n`/Users/andy/Workspace/codes/ai/nova`"),
        ]
    )
    _init_test_repl(repl)
    repl._pending_input = None
    repl._streaming = False
    repl._stop_requested = False
    repl._input_ui = None
    repl.create_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    monkeypatch.setattr(repl._display, "info", lambda text: captured.append(text))
    monkeypatch.setattr(repl._display, "error", lambda text: captured.append(f"ERROR::{text}"))

    monkeypatch.setattr(repl._display.spinner, "stop", lambda: None)
    monkeypatch.setattr(repl._display, "flush", lambda: None)
    monkeypatch.setattr(repl._display.spinner, "start_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(repl._display.spinner, "start_tool", lambda *args, **kwargs: None)
    monkeypatch.setattr(repl._display, "_stream_text", lambda text: None)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    await repl.run_stream("hi")

    assert captured == []


@pytest.mark.asyncio
async def test_run_stream_shows_edit_diff_on_success(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent(
        [
            (AgentEvent.TOOL_CALL, type("ToolCallStub", (), {"name": "edit", "arguments": '{"filePath":"foo.py"}'})()),
            (
                AgentEvent.TOOL_RESULT,
                {
                    "tool": "edit",
                    "tool_call_id": "call_1",
                    "result": ToolResult(
                        success=True,
                        content="Changes applied to foo.py:\n\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n",
                    ),
                },
            ),
            (AgentEvent.DONE, {"reason": "completed", "content": "Finished"}),
        ]
    )
    _init_test_repl(repl)
    repl._pending_input = None
    repl._streaming = False
    repl._stop_requested = False
    repl._input_ui = None
    repl.create_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    monkeypatch.setattr(repl._display, "info", lambda text: captured.append(text))
    monkeypatch.setattr(repl._display, "error", lambda text: captured.append(f"ERROR::{text}"))

    monkeypatch.setattr(repl._display.spinner, "stop", lambda: None)
    monkeypatch.setattr(repl._display, "flush", lambda: None)
    monkeypatch.setattr(repl._display.spinner, "start_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(repl._display.spinner, "start_tool", lambda *args, **kwargs: None)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: captured.append(" ".join(str(arg) for arg in args)))

    await repl.run_stream("hi")

    diff_output = "\n".join(captured)
    assert "\033[1;36m--- a/foo.py\033[0m" in diff_output
    assert "\033[1;36m+++ b/foo.py\033[0m" in diff_output
    assert "\033[31m-old\033[0m" in diff_output
    assert "\033[32m+new\033[0m" in diff_output


@pytest.mark.asyncio
async def test_run_stream_skips_redundant_requires_input_done_message(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent(
        [
            (AgentEvent.TOOL_CALL, type("ToolCallStub", (), {"name": "ask_user", "arguments": '{"question":"city"}'})()),
            (
                AgentEvent.TOOL_RESULT,
                {
                    "tool": "ask_user",
                    "tool_call_id": "call_1",
                    "result": ToolResult(
                        success=True,
                        requires_input=True,
                        content='{"question":{"header":"Current City","question":"Please tell me which city you want the weather for.","input_type":"text","options":[]}}',
                    ),
                },
            ),
            (AgentEvent.DONE, {"reason": "requires_input", "content": "User input required"}),
        ]
    )
    _init_test_repl(repl)
    repl._pending_input = None
    repl._streaming = False
    repl._stop_requested = False
    repl._input_ui = None
    repl.create_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    monkeypatch.setattr(repl._display, "info", lambda text: captured.append(text))
    monkeypatch.setattr(repl._display, "error", lambda text: captured.append(f"ERROR::{text}"))

    monkeypatch.setattr(repl._display.spinner, "stop", lambda: None)
    monkeypatch.setattr(repl._display, "flush", lambda: None)
    monkeypatch.setattr(repl._display.spinner, "start_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(repl._display.spinner, "start_tool", lambda *args, **kwargs: None)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    await repl.run_stream("weather")

    assert captured == []
    assert repl._pending_input is not None


@pytest.mark.asyncio
async def test_pending_input_json_uses_human_prompt(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    _init_test_repl(repl)
    repl._command_registry = CommandRegistry()
    repl._command_dispatcher = CommandDispatcher(
        registry=repl._command_registry,
        handlers={},
    )
    repl._pending_input = {
        "content": '{"question":{"header":"Current City","question":"Please tell me which city you want the weather for.","input_type":"text","options":[]}}'
    }
    repl._streaming = False
    repl._stop_requested = False
    repl._running = True
    repl._input_ui = None
    repl.create_cancel_monitor = lambda callback: _FakeMonitor()
    repl._prompt_followup = lambda body: body
    repl.run_stream = lambda user_input: None

    prompted = []

    async def fake_prompt(body):
        prompted.append(body)
        repl._running = False
        return "Maanshan"

    async def fake_run_stream(user_input):
        repl._running = False

    repl._prompt_followup = fake_prompt
    repl.run_stream = fake_run_stream

    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    await repl.run()

    clean_prompted = [re.sub(r"\x1b\[[0-9;]*m", "", text) for text in prompted]
    assert clean_prompted == ["  ? Current City\n  Please tell me which city you want the weather for."]


@pytest.mark.asyncio
async def test_handle_user_turn_renders_user_message_before_stream(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    _init_test_repl(repl)
    repl._command_registry = CommandRegistry()
    repl._command_dispatcher = CommandDispatcher(
        registry=repl._command_registry,
        handlers={},
    )

    events: list[tuple[str, str]] = []

    async def fake_prompt():
        return "hello"

    async def fake_run_stream(user_input):
        events.append(("run_stream", user_input))

    monkeypatch.setattr(repl._display, "print_user_message", lambda text: events.append(("print_user_message", text)))
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    repl._prompt_chat = fake_prompt
    repl.run_stream = fake_run_stream

    await repl._handle_user_turn()

    assert events == [
        ("print_user_message", "hello"),
        ("run_stream", "hello"),
    ]


@pytest.mark.asyncio
async def test_pending_input_invalid_payload_shows_error(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    _init_test_repl(repl)
    repl._command_registry = CommandRegistry()
    repl._command_dispatcher = CommandDispatcher(
        registry=repl._command_registry,
        handlers={},
    )
    repl._pending_input = {"content": "not-json"}
    repl._streaming = False
    repl._stop_requested = False
    repl._running = True
    repl._input_ui = None
    repl.create_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    monkeypatch.setattr(
        repl._display,
        "error",
        lambda text: (captured.append(text), setattr(repl, "_running", False)),
    )

    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    await repl.run()

    assert captured == ["Invalid ask_user payload."]


@pytest.mark.asyncio
async def test_pending_input_old_array_payload_shows_error(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    _init_test_repl(repl)
    repl._command_registry = CommandRegistry()
    repl._command_dispatcher = CommandDispatcher(
        registry=repl._command_registry,
        handlers={},
    )
    repl._pending_input = {
        "content": '{"questions":[{"header":"Question 1","question":"First question","input_type":"text","options":[]},{"header":"Question 2","question":"Second question","input_type":"text","options":[]}]}'
    }
    repl._streaming = False
    repl._stop_requested = False
    repl._running = True
    repl._input_ui = None
    repl.create_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    monkeypatch.setattr(
        repl._display,
        "error",
        lambda text: (captured.append(text), setattr(repl, "_running", False)),
    )

    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    await repl.run()

    assert captured == ["Invalid ask_user payload."]
