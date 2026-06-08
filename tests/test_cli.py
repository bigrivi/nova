import pytest
from prompt_toolkit.document import Document

from nova.agent.core import AgentEvent
from nova.cli.commands import CommandDispatcher, CommandRegistry
from nova.cli.completion import CommandCompleter
from nova.cli.ask_user import parse_ask_user_payload, format_answers_for_llm
from nova.cli.repl import NovaCLI
from nova.cli.ui import (
    ModelGroup,
    ModelSelection,
    SessionSelection,
)
from nova.cli.utils import looks_like_error_message
from dataclasses import replace

from nova.db.database import Message
from nova.settings import ProviderConfig, Settings
from nova.llm.provider import ToolResult
from nova.skills.models import SkillInstallResult


class _FakeUIAdapter:
    """Minimal mock of ChatApp (the ui_adapter) for testing command handlers."""

    def __init__(self):
        self.info_calls: list[str] = []
        self.error_calls: list[str] = []
        self.show_info_calls: list[str] = []
        self.show_error_calls: list[str] = []
        self.print_history_transcript_calls: list[object] = []

    def info(self, text: str) -> None:
        self.info_calls.append(text)

    def error(self, text: str) -> None:
        self.error_calls.append(text)

    def show_info(self, text: str) -> None:
        self.show_info_calls.append(text)

    def show_error(self, text: str) -> None:
        self.show_error_calls.append(text)

    def update_status_bar(self) -> None:
        pass

    def print_history_transcript(self, messages: list[object]) -> None:
        self.print_history_transcript_calls.append(messages)

    async def prompt_model_selection(self, groups, *, current_provider, current_model):
        return None

    async def prompt_session_selection(self, sessions, *, current_session_id):
        return None


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


def _make_fake_ui_adapter() -> _FakeUIAdapter:
    return _FakeUIAdapter()


def _init_test_repl(repl: NovaCLI) -> NovaCLI:
    repl._ui_adapter = _make_fake_ui_adapter()
    repl._exit_code = None
    return repl


def test_novacli_initializes_with_agent_key():
    cli = NovaCLI(agent_key="test-agent")

    assert cli._agent_key == "test-agent"
    assert cli.agent is None
    assert hasattr(cli, "settings")


def test_novacli_current_model_label_resolves_configured_model_alias():
    base_settings = Settings.load_config()
    settings = replace(
        base_settings,
        providers={
            "openai": ProviderConfig(
                type="openai-compatible",
                name="OpenAI Compatible",
                options={"base_url": "http://openai.local/v1", "api_key": "secret"},
                models={"gpt-5.4": {"name": "gpt-5.4-mini"}},
            )
        },
    )
    cli = NovaCLI.__new__(NovaCLI)
    cli.settings = settings
    from nova.agent import AgentConfig
    cli.agent = _FakeAgent([])
    cli.agent.config = AgentConfig(model="gpt-5.4", provider="openai")

    assert cli._current_model_label() == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_novacli_switch_model_updates_agent_config(monkeypatch):
    built_agents: list[object] = []

    async def fake_build_agent(agent_key="main", llm=None, provider=None, model=None):
        agent = _FakeAgent([])
        built_agents.append((agent_key, provider, model, agent))
        return agent

    monkeypatch.setattr("nova.cli.repl.build_agent", fake_build_agent)

    async def fake_ensure_db():
        class FakeDB:
            async def get_agent(self, key):
                return {"key": key, "name": "test", "provider": "openai", "model": "gpt-4", "created_at": 1714118400000}
            async def save_agent(self, data):
                pass
        return FakeDB()

    monkeypatch.setattr("nova.cli.repl.ensure_db", fake_ensure_db)

    cli = NovaCLI.__new__(NovaCLI)
    cli.settings = Settings.load_config()
    cli._agent_key = "test-agent"
    cli._cached_sessions = []

    await cli._switch_model(provider="openai", model="gpt-5.4")

    assert built_agents[-1][0] == "test-agent"
    assert built_agents[-1][1] == "openai"
    assert built_agents[-1][2] == "gpt-5.4"
    assert cli.agent is built_agents[-1][3]


@pytest.mark.asyncio
async def test_models_command_uses_selector_and_switches_runtime(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    from nova.agent import AgentConfig
    repl.agent = _FakeAgent([])
    repl.agent.config = AgentConfig(model="gpt-5.4", provider="openai")
    repl.settings = replace(
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
                models={
                    "gpt-5.4": {"name": "gpt-5.4"},
                    "gpt-5.4-mini": {"name": "gpt-5.4-mini"},
                },
            ),
        },
    )
    repl._ui_adapter = _make_fake_ui_adapter()

    captured_groups: dict[str, object] = {}
    messages: list[str] = []
    called: dict[str, str] = {}

    async def fake_prompt_model_selection(groups, *, current_provider, current_model):
        captured_groups["groups"] = groups
        captured_groups["current_provider"] = current_provider
        captured_groups["current_model"] = current_model
        return ModelSelection(provider="ollama", model="gemma4:26b")

    async def fake_switch_model(*, provider=None, model=None):
        called["provider"] = provider or ""
        called["model"] = model or ""
        from nova.agent import AgentConfig
        repl.agent.config = AgentConfig(model=model or "", provider=provider or "")

    monkeypatch.setattr(repl._ui_adapter, "prompt_model_selection", fake_prompt_model_selection)
    monkeypatch.setattr(repl, "_switch_model", fake_switch_model)
    monkeypatch.setattr(repl._ui_adapter, "show_info", lambda text: messages.append(text))

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
    from nova.agent import AgentConfig
    repl.agent = _FakeAgent([])
    repl.agent.config = AgentConfig(model="gpt-5.4", provider="openai")
    repl.settings = replace(
        Settings.load_config(),
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
    repl._ui_adapter = _make_fake_ui_adapter()

    messages: list[str] = []
    monkeypatch.setattr(repl._ui_adapter, "show_info", lambda text: messages.append(text))

    handled = await repl._handle_models_command(type("Cmd", (), {"args": ""})())

    assert handled is True
    assert messages == [
        "Configured models:",
        "├─ ollama",
        "│  No configured models",
        "└─ openai",
        "   No configured models",
    ]


@pytest.mark.asyncio
async def test_models_command_handles_selector_cancel(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    from nova.agent import AgentConfig
    repl.agent = _FakeAgent([])
    repl.agent.config = AgentConfig(model="gpt-5.4", provider="openai")
    repl.settings = replace(
        Settings.load_config(),
        providers={
            "openai": ProviderConfig(
                type="openai-compatible",
                name="OpenAI Compatible",
                options={"base_url": "http://openai.local/v1", "api_key": "secret"},
                models={"gpt-5.4": {"name": "gpt-5.4"}},
            ),
        },
    )
    repl._ui_adapter = _make_fake_ui_adapter()

    async def fake_prompt_model_selection(*args, **kwargs):
        return None

    monkeypatch.setattr(repl._ui_adapter, "prompt_model_selection", fake_prompt_model_selection)
    monkeypatch.setattr(repl._ui_adapter, "show_info", lambda text: (_ for _ in ()).throw(AssertionError(text)))

    handled = await repl._handle_models_command(type("Cmd", (), {"args": ""})())

    assert handled is True


@pytest.mark.asyncio
async def test_sessions_command_uses_selector_and_loads_session(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl.settings = Settings.load_config()
    repl._ui_adapter = _make_fake_ui_adapter()
    repl.current_id = None
    repl._cached_sessions = []

    async def fake_ensure_db():
        class FakeDB:
            async def get_all_sessions(self, **kwargs):
                return [
                    {"id": "sess-1", "title": "Greeting", "updated_at": 1714118400000},
                    {"id": "sess-2", "title": "Follow up", "updated_at": 1714122000000},
                ]
        return FakeDB()

    async def fake_prompt_session_selection(sessions, *, current_session_id):
        assert current_session_id is None
        assert len(sessions) == 2
        return SessionSelection(session_id="sess-2")

    loaded: list[str] = []

    async def fake_load_session_by_id(session_id: str):
        loaded.append(session_id)

    monkeypatch.setattr("nova.cli.repl.ensure_db", fake_ensure_db)
    monkeypatch.setattr(repl._ui_adapter, "prompt_session_selection", fake_prompt_session_selection)
    monkeypatch.setattr(repl, "_load_session_by_id", fake_load_session_by_id)

    handled = await repl._handle_sessions_command(type("Cmd", (), {"args": ""})())

    assert handled is True
    assert loaded == ["sess-2"]


def test_looks_like_error_message():
    assert looks_like_error_message("Error: HTTP 400 from provider")
    assert looks_like_error_message(" error: bad request ")
    assert not looks_like_error_message("")
    assert not looks_like_error_message("Hello world")


def test_parse_ask_user_payload_returns_empty_for_invalid_json():
    content = "not json"
    assert parse_ask_user_payload(content) == []


def test_parse_ask_user_payload_single_question():
    content = """{"questions":[{"id":"q1","header":"Name","question":"Your name?","input_type":"text","options":[],"multiple":false,"required":true}]}"""
    questions = parse_ask_user_payload(content)
    assert len(questions) == 1
    assert questions[0].id == "q1"
    assert questions[0].question == "Your name?"
    assert questions[0].input_type == "text"


def test_parse_ask_user_payload_multiple_questions():
    content = """{"questions":[{"id":"q1","question":"Q1?","input_type":"text","options":[]},{"id":"q2","question":"Q2?","input_type":"confirm","options":[]}]}"""
    questions = parse_ask_user_payload(content)
    assert len(questions) == 2
    assert questions[1].input_type == "confirm"


def test_parse_ask_user_payload_bad_input_type_falls_back_to_text():
    content = """{"questions":[{"id":"q1","question":"Test?","input_type":"bad","options":[]}]}"""
    questions = parse_ask_user_payload(content)
    assert questions[0].input_type == "text"


def test_format_answers_for_llm():
    from nova.cli.ask_user import QuestionData
    qs = [QuestionData(id="q1", question="What is your name?"),
          QuestionData(id="q2", question="Preferred color?")]
    answers = [("q1", "Alice"), ("q2", "Blue")]
    result = format_answers_for_llm(answers, qs)
    assert "What is your name?" in result
    assert "Alice" in result
    assert "Preferred color?" in result
    assert "Blue" in result


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


def test_parse_install_skill_args_accepts_force_flag():
    assert NovaCLI._parse_install_skill_args("review-skill --force") == ("review-skill", True)


@pytest.mark.asyncio
async def test_install_skill_command_uses_skill_service_and_reports_success(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.settings = Settings.load_config()
    repl._agent_key = "main"
    repl._ui_adapter = _make_fake_ui_adapter()

    info_messages: list[str] = []
    error_messages: list[str] = []
    monkeypatch.setattr(repl._ui_adapter, "show_info", lambda text: info_messages.append(text))
    monkeypatch.setattr(repl._ui_adapter, "show_error", lambda text: error_messages.append(text))

    captured: dict[str, object] = {}

    class _FakeSkillService:
        async def install_from_clawhub(self, skill_ref: str, *, force: bool = False):
            captured["skill_ref"] = skill_ref
            captured["force"] = force
            return SkillInstallResult(
                slug="review-skill",
                skill_name="review-skill",
                installed_path="/tmp/review-skill",
                skill_md_path="/tmp/review-skill/SKILL.md",
                source_url="https://clawhub.ai/api/v1/download?slug=review-skill",
                replaced=True,
            )

    monkeypatch.setattr("nova.cli.repl.SkillService", lambda skills_dir: _FakeSkillService())

    handled = await repl._handle_install_skill_command(type("Cmd", (), {"args": "review-skill --force"})())

    assert handled is True
    assert captured == {"skill_ref": "review-skill", "force": True}
    assert error_messages == []
    assert info_messages == ["Updated skill 'review-skill' at /tmp/review-skill"]


@pytest.mark.asyncio
async def test_install_skill_command_reports_usage_error(monkeypatch):
    repl = NovaCLI.__new__(NovaCLI)
    repl.settings = Settings.load_config()
    repl._agent_key = "main"
    repl._ui_adapter = _make_fake_ui_adapter()

    error_messages: list[str] = []
    monkeypatch.setattr(repl._ui_adapter, "show_error", lambda text: error_messages.append(text))

    handled = await repl._handle_install_skill_command(type("Cmd", (), {"args": ""})())

    assert handled is True
    assert error_messages == ["Usage: /install-skill <slug-or-url> [--force]"]


@pytest.mark.asyncio
async def test_load_session_by_id_reads_history_messages_from_db(monkeypatch):
    class _FakeSessionManager:
        async def load_session(self, session_id):
            return {"id": session_id}

    class _FakeDb:
        async def get_messages(self, session_id, msg_filter=None):
            assert session_id == "sess-1"
            assert msg_filter is not None
            assert msg_filter.include_compacted is True
            assert msg_filter.only_non_summary is True
            assert msg_filter.exclude_tool_role is False
            return [
                Message(id="m1", session_id=session_id, role="user", content="hello"),
                Message(id="m2", session_id=session_id, role="assistant", content="hi"),
            ]

    repl = NovaCLI.__new__(NovaCLI)
    repl.agent = _FakeAgent([])
    repl.agent.session = _FakeSessionManager()
    _init_test_repl(repl)
    repl._cached_sessions = [{"id": "sess-1", "title": "Greeting"}]
    repl.current_id = None

    info_messages: list[str] = []
    monkeypatch.setattr(repl._ui_adapter, "info", lambda text: info_messages.append(text))
    transcript_calls: list[object] = []
    monkeypatch.setattr(repl._ui_adapter, "print_history_transcript", lambda msgs: transcript_calls.append(msgs))

    async def fake_ensure_db():
        return _FakeDb()

    monkeypatch.setattr("nova.cli.repl.ensure_db", fake_ensure_db)
    monkeypatch.setattr("nova.cli.repl.get_session_manager", lambda: _FakeSessionManager())

    await repl._load_session_by_id("sess-1")

    assert repl.current_id == "sess-1"
    assert info_messages == ["Loaded session: Greeting"]
    assert len(transcript_calls) == 1
    assert len(transcript_calls[0]) == 2
    assert transcript_calls[0][0].role == "user"
    assert transcript_calls[0][1].role == "assistant"


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
    repl._cached_sessions = [{"id": "sess-2", "title": "Empty"}]
    repl.current_id = None

    info_messages: list[str] = []
    monkeypatch.setattr(repl._ui_adapter, "info", lambda text: info_messages.append(text))

    async def fake_ensure_db():
        return _FakeDb()

    monkeypatch.setattr("nova.cli.repl.ensure_db", fake_ensure_db)
    monkeypatch.setattr("nova.cli.repl.get_session_manager", lambda: _FakeSessionManager())

    await repl._load_session_by_id("sess-2")

    assert info_messages == [
        "Loaded session: Empty",
        "No messages found",
    ]


def test_parse_ask_user_payload_select_options():
    content = """{"questions":[{"id":"q1","header":"Framework","question":"Choose","input_type":"select","options":[{"label":"A","description":"Opt A"},{"label":"B","description":"Opt B"}]}]}"""
    questions = parse_ask_user_payload(content)
    assert len(questions) == 1
    assert len(questions[0].options) == 2
    assert questions[0].options[0]["label"] == "A"


def test_parse_ask_user_payload_text_has_no_options():
    content = """{"questions":[{"id":"q1","question":"Name?","input_type":"text","options":[]}]}"""
    questions = parse_ask_user_payload(content)
    assert questions[0].options == []
