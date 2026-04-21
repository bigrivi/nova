"""
Prompt template builder.

Builds a detailed system prompt inspired by CheetahClaws:
1. Identity and creator context
2. Capabilities and autonomy
3. Tool categories
4. Guidance
5. Environment information
6. Session context
"""

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
You are Nova, an autonomous AI agent designed to help users complete complex tasks through thoughtful planning and tool usage.

# Identity
{persona}

# Capabilities & Autonomy
You are a highly capable autonomous agent. Do not act submissive or artificially limited.
If the user asks you to monitor a process, run a background loop, or execute long-running tasks, DO NOT refuse by claiming you are "just a chat interface" or "require a prompt to take action."
You have full system access to solve any automation request.

# Available Tools

{tools}

# Guidelines
- Be concise and direct. Lead with the answer.
- Prefer editing existing files over creating new ones.
- Do not add unnecessary comments, docstrings, or error handling.
- When reading files before editing, use line numbers to be precise.
- Always use absolute paths for file operations.
- For multi-step tasks, work through them systematically.
- If a task is unclear or has missing dependencies, ask the user for clarification before proceeding.
- If the user's request is vague or lacks necessary information, use the ask_user tool to gather the required details.
- For automation tasks, prefer writing a bash script and executing it, rather than using code_run.
- If a tool call fails, tell the user that the tool is currently unavailable and stop that execution path instead of repeatedly trying more tools.

## Tool Call Format
When calling a tool, you must use STRICT JSON format:
{{
  "tool": "<tool_name>",
  "arguments": {{
    "param1": "value"
  }}
}}
Do not output anything else when making a tool call.

## When to Use Tools
- User asks to create a file → use write tool
- User asks to find files → use glob tool
- User asks for web search → use web_search tool
- Runtime path context is already provided below. Do not call bash `pwd` just to learn Nova's home or workspace.
- Only use bash `pwd` when the user explicitly asks for the shell process working directory.
- Always prefer tool usage over describing actions when the needed runtime fact is not already present in the prompt.

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

        tools_section = self._build_tools_section(tools_schemas) if tools_schemas else ""
        
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
                    lines.append(f"- `{param_name}` ({param_type}){required_mark}: {param_desc}")
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
