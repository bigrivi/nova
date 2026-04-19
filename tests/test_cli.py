import pytest

from nova.agent.core import AgentEvent
from nova.cli.interactive import NovaCLI, _looks_like_error_message, parse_options
from dataclasses import replace

from nova.settings import Settings


class _FakeMonitor:
    def start(self):
        return None

    def stop(self):
        return None


class _FakeAgent:
    def __init__(self, events):
        self._events = events

    async def chat_stream(self, user_input, session_id=None):
        for item in self._events:
            yield item


def test_novacli_builds_runtime_from_settings(monkeypatch):
    captured = {}

    def fake_build_agent(settings):
        captured["settings"] = settings
        return _FakeAgent([])

    monkeypatch.setattr(
        "nova.cli.interactive.build_agent",
        fake_build_agent,
    )
    settings = replace(
        Settings.from_env(),
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


def test_looks_like_error_message():
    assert _looks_like_error_message("Error: HTTP 400 from provider")
    assert _looks_like_error_message(" error: bad request ")
    assert not _looks_like_error_message("")
    assert not _looks_like_error_message("Hello world")


@pytest.mark.asyncio
async def test_run_shows_cli_banner_with_slash_commands(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl._current_session_id = None
    repl._pending_input = None
    repl._streaming = False
    repl._stop_requested = False
    repl._stream_cancel_monitor = None
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
    assert "Use /new, /sessions, /load <n>, /clear, or /quit for commands." in captured


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
    repl._current_session_id = None
    repl._pending_input = None
    repl._streaming = False
    repl._stop_requested = False
    repl._stream_cancel_monitor = None
    repl._create_stream_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    repl._show_info = lambda text: captured.append(text)
    repl._show_error = lambda text: captured.append(f"ERROR::{text}")

    monkeypatch.setattr("nova.cli.interactive._stop_spinner", lambda: None)
    monkeypatch.setattr("nova.cli.interactive._flush_stream", lambda: None)
    monkeypatch.setattr("nova.cli.interactive._start_spinner", lambda: None)

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
    repl._current_session_id = None
    repl._pending_input = None
    repl._streaming = False
    repl._stop_requested = False
    repl._stream_cancel_monitor = None
    repl._create_stream_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    repl._show_info = lambda text: captured.append(text)
    repl._show_error = lambda text: captured.append(f"ERROR::{text}")

    monkeypatch.setattr("nova.cli.interactive._stop_spinner", lambda: None)
    monkeypatch.setattr("nova.cli.interactive._flush_stream", lambda: None)
    monkeypatch.setattr("nova.cli.interactive._start_spinner", lambda: None)
    monkeypatch.setattr("nova.cli.interactive._stream_text", lambda text: None)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    await repl.run_stream("hi")

    assert captured == []


@pytest.mark.asyncio
async def test_pending_input_json_uses_human_prompt(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl._current_session_id = None
    repl._pending_input = {
        "content": '{"question":{"header":"Current City","question":"Please tell me which city you want the weather for.","input_type":"text","options":[]}}'
    }
    repl._streaming = False
    repl._stop_requested = False
    repl._stream_cancel_monitor = None
    repl._running = True
    repl._create_stream_cancel_monitor = lambda callback: _FakeMonitor()
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

    assert prompted == ["Current City\nPlease tell me which city you want the weather for."]


@pytest.mark.asyncio
async def test_pending_input_invalid_payload_shows_error(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl._current_session_id = None
    repl._pending_input = {"content": "not-json"}
    repl._streaming = False
    repl._stop_requested = False
    repl._stream_cancel_monitor = None
    repl._running = True
    repl._create_stream_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    repl._show_error = lambda text: (captured.append(text), setattr(repl, "_running", False))

    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    await repl.run()

    assert captured == ["Invalid ask_user payload."]


@pytest.mark.asyncio
async def test_pending_input_old_array_payload_shows_error(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl._current_session_id = None
    repl._pending_input = {
        "content": '{"questions":[{"header":"Question 1","question":"First question","input_type":"text","options":[]},{"header":"Question 2","question":"Second question","input_type":"text","options":[]}]}'
    }
    repl._streaming = False
    repl._stop_requested = False
    repl._stream_cancel_monitor = None
    repl._running = True
    repl._create_stream_cancel_monitor = lambda callback: _FakeMonitor()

    captured = []
    repl._show_error = lambda text: (captured.append(text), setattr(repl, "_running", False))

    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    await repl.run()

    assert captured == ["Invalid ask_user payload."]
