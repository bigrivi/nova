"""
Test PromptBuilder
"""

import pytest

from nova.prompt import PromptBuilder, SessionContext, ContextStats, build_system_prompt


class TestPromptBuilder:
    def test_basic_prompt(self):
        builder = PromptBuilder()
        prompt = builder.build()
        assert "Nova" in prompt
        assert "You are Nova" in prompt
        assert "tool is currently unavailable" in prompt
        assert "STRICT JSON format" in prompt
        assert '"tool": "<tool_name>"' in prompt

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
