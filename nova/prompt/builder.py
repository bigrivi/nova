"""Prompt template builder."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from nova.settings import get_settings


@dataclass
class PromptConfig:
    persona: str = "You are Nova, a helpful AI assistant."
    include_context_stats: bool = True
    include_session_context: bool = True


@dataclass
class SessionContext:
    session_id: str = ""
    title: str = ""
    goal: str = ""
    accomplished: str = ""
    remaining: str = ""
    turn_count: int = 0


@dataclass
class ContextStats:
    model: str = "gpt-4o"
    max_tokens: int = 128000
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    usage_percent: float = 0.0
    messages_count: int = 0

    def render_progress_bar(self) -> str:
        bar_length = 20
        filled = int(bar_length * self.usage_percent / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        warning = " ⚠️" if self.usage_percent > 70 else ""
        return f"[{bar}] {self.usage_percent:.1f}%{warning}"

    def render_stats(self) -> str:
        lines = [
            "",
            "## Context Status",
            f"Model: {self.model}",
            f"Progress: {self.render_progress_bar()}",
            f"Tokens: {self.input_tokens:,} in / {self.output_tokens:,} out",
            f"Messages: {self.messages_count}",
        ]
        if self.usage_percent > 70:
            lines.append("⚠️ Context nearing limit")
        return "\n".join(lines)


class PromptBuilder:
    SYSTEM_PROMPT_TEMPLATE = """\
You are Nova, a personal AI assistant and autonomous AI agent.
You help the user complete a wide range of practical tasks.
You can proactively use available tools to move work forward when that is useful and safe.

# Identity
{persona}

# Working Style
- Be concise and direct.
- Prefer doing the work with tools instead of only describing it.
- If information is missing and the task cannot proceed safely, ask for clarification.
- If clarification is needed during execution, use `ask_user`.
- If a tool call fails, use the error to adjust the next step. Do not blindly retry the same failing call.

# Available Tools

{tools}

## Tool Call Format
When calling a tool, output JSON only:
{{
  "name": "<tool_name>",
  "arguments": {{
    "param1": "value"
  }}
}}
- MUST use key "name", NOT "tool"
- Do NOT output anything else with the tool call

# Tool Usage
- Prefer tool usage when the required runtime fact is not already present in the prompt.
- Runtime path context is already provided below. Do not call bash `pwd` just to learn Nova's home or workspace.
- Only use bash `pwd` when the user explicitly asks for the shell process working directory.

# Environment
- Current date: {date}
- Nova home: {home}
- Nova workspace: {workspace_dir}
- Platform: {platform}
"""

    def __init__(self, config: Optional[PromptConfig] = None):
        self.config = config or PromptConfig()

    def build(
        self,
        tools_schemas: list[dict] = None,
        session_context: SessionContext = None,
        context_stats: ContextStats = None,
    ) -> str:
        parts = []
        settings = get_settings()

        tools_section = self._build_tools_section(
            tools_schemas) if tools_schemas else ""

        parts.append(self.SYSTEM_PROMPT_TEMPLATE.format(
            persona=self.config.persona,
            tools=tools_section,
            date=datetime.now().strftime("%Y-%m-%d %A"),
            home=settings.home,
            workspace_dir=settings.workspace_dir,
            platform=self._get_platform(),
        ))

        if session_context and self.config.include_session_context:
            parts.append(self._build_session_context(session_context))

        if context_stats and self.config.include_context_stats:
            parts.append(context_stats.render_stats())

        return "\n\n".join(parts)

    def _get_platform(self) -> str:
        import platform
        return platform.system()

    def _build_tools_section(self, tools_schemas: list[dict]) -> str:
        if not tools_schemas:
            return "No tools available."

        lines = []
        for tool in tools_schemas:
            func = tool.get("function", tool)
            name = func.get("name", "unknown")
            desc = func.get("description", "No description available")
            params = func.get("parameters", {})

            lines.append(f"## {name}")
            lines.append(f"{desc}")

            props = params.get("properties", {})
            required = params.get("required", [])

            if props:
                lines.append("**Parameters:**")
                for param_name, param_info in props.items():
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    required_mark = " (required)" if param_name in required else " (optional)"
                    lines.append(
                        f"- `{param_name}` ({param_type}){required_mark}: {param_desc}")
            lines.append("")

        return "\n".join(lines)

    def _build_session_context(self, ctx: SessionContext) -> str:
        lines = ["## Current Session\n"]

        if ctx.title:
            lines.append(f"**Title:** {ctx.title}\n")

        if ctx.goal:
            lines.append(f"**Goal:** {ctx.goal}\n")

        if ctx.accomplished:
            lines.append(f"**Accomplished:** {ctx.accomplished}\n")

        if ctx.remaining:
            lines.append(f"**Remaining:** {ctx.remaining}\n")

        if ctx.turn_count > 0:
            lines.append(f"**Turns:** {ctx.turn_count}\n")

        return "\n".join(lines)


def build_system_prompt(
    tools_schemas: list[dict] = None,
    session_context: SessionContext = None,
    context_stats: ContextStats = None,
    config: PromptConfig = None,
) -> str:
    builder = PromptBuilder(config)
    return builder.build(tools_schemas, session_context, context_stats)
