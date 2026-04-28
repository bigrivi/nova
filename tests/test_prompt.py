"""
Test PromptBuilder
"""

import pytest

from nova.prompt import PromptBuilder, SessionContext, ContextStats, build_system_prompt
from nova.settings import Settings
from nova.skills.models import SkillSummary


class TestPromptBuilder:
    @pytest.fixture(autouse=True)
    def _stub_settings(self, monkeypatch, tmp_path):
        home = tmp_path / "nova-home"
        workspace = home / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        settings = Settings(
            home=home,
            workspace_dir=workspace,
            logs_dir=home / "logs",
            database_path=home / "nova.db",
            host="127.0.0.1",
            backend_port=8765,
            ui_port=8501,
            log_level="INFO",
            provider="ollama",
            model="gemma4:26b",
            ollama_base_url="http://localhost:11434",
            openai_base_url="https://api.openai.com/v1",
            openai_api_key="",
        )
        monkeypatch.setattr("nova.prompt.builder.get_settings", lambda: settings)
        return settings

    def test_basic_prompt(self):
        builder = PromptBuilder()
        prompt = builder.build()
        assert "Nova" in prompt
        assert "You are Nova, a personal AI assistant and autonomous AI agent." in prompt
        assert "complete a wide range of practical tasks" in prompt
        assert "If a tool call fails, use the error to adjust the next step." in prompt
        assert "If clarification is needed during execution, use `ask_user`." in prompt
        assert "output JSON only" in prompt
        assert '"name": "<tool_name>"' in prompt
        assert '"tool": "<tool_name>"' not in prompt
        assert "Nova home:" in prompt
        assert "Nova workspace:" in prompt
        assert "shell process working directory" in prompt
        assert "Skills are dynamic." in prompt
        assert "Current Available Skills" in prompt
        assert "Call `list_skills`" in prompt
        assert "call `list_skills` early" in prompt
        assert "Call `load_skill`" in prompt
        assert "call `load_skill` before doing the workflow from memory" in prompt
        assert "Only call `install_skill`" in prompt
        assert "call `list_skills` before `install_skill`" in prompt
        assert "prefer `load_skill` instead of reinstalling" in prompt
        assert 'what directory am I in" → use bash tool with "pwd"' not in prompt
        assert "Git branch:" not in prompt
        assert "Capabilities & Autonomy" not in prompt

    def test_with_tools(self):
        tools = [
            {
                "name": "read",
                "description": "Read file contents",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filePath": {
                            "type": "string",
                            "description": "The file path"
                        }
                    },
                    "required": ["filePath"]
                }
            }
        ]
        builder = PromptBuilder()
        prompt = builder.build(tools_schemas=tools)
        assert "# Available Tools" in prompt
        assert "read" in prompt
        assert "filePath" in prompt

    def test_prompt_includes_available_skill_summaries(self):
        builder = PromptBuilder()
        prompt = builder.build(
            available_skills=[
                SkillSummary(
                    name="code-review",
                    description="Review code changes.",
                    path="/tmp/skills/code-review",
                    skill_md_path="/tmp/skills/code-review/SKILL.md",
                ),
                SkillSummary(
                    name="12306",
                    description="Help with railway ticket workflows.",
                    path="/tmp/skills/12306",
                    skill_md_path="/tmp/skills/12306/SKILL.md",
                ),
            ]
        )

        assert "- code-review: Review code changes." in prompt
        assert "- 12306: Help with railway ticket workflows." in prompt
        assert "call `load_skill` with the exact skill name" in prompt

    def test_prompt_mentions_when_no_skills_are_installed(self):
        builder = PromptBuilder()
        prompt = builder.build(available_skills=[])

        assert "- No skills currently installed in the runtime catalog." in prompt

    def test_with_session_context(self):
        ctx = SessionContext(
            session_id="test-123",
            title="Test Session",
            goal="Complete the task",
            accomplished="Step 1 done",
            remaining="Step 2",
            turn_count=5,
        )
        builder = PromptBuilder()
        prompt = builder.build(session_context=ctx)
        assert "Test Session" in prompt
        assert "Complete the task" in prompt
        assert "5" in prompt

    def test_with_context_stats(self):
        stats = ContextStats(
            model="gpt-4o",
            max_tokens=128000,
            input_tokens=1000,
            output_tokens=500,
            usage_percent=1.2,
            messages_count=10,
        )
        builder = PromptBuilder()
        prompt = builder.build(context_stats=stats)
        assert "Context Status" in prompt
        assert "gpt-4o" in prompt
        assert "10" in prompt

    def test_full_prompt(self):
        tools = [
            {
                "name": "bash",
                "description": "Execute shell commands",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to execute"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds"}
                    },
                    "required": ["command"]
                }
            }
        ]
        ctx = SessionContext(
            title="Development Task",
            goal="Build a feature",
            turn_count=3,
        )
        stats = ContextStats(
            model="gemma4:26b",
            usage_percent=15.5,
            messages_count=6,
        )
        
        prompt = build_system_prompt(
            tools_schemas=tools,
            session_context=ctx,
            context_stats=stats,
        )
        
        assert "Nova" in prompt
        assert "# Available Tools" in prompt
        assert "bash" in prompt
        assert "Development Task" in prompt
        assert "Context Status" in prompt

    def test_prompt_uses_settings_runtime_paths(self, _stub_settings):
        builder = PromptBuilder()
        prompt = builder.build()
        assert f"Nova home: {_stub_settings.home}" in prompt
        assert f"Nova workspace: {_stub_settings.workspace_dir}" in prompt
