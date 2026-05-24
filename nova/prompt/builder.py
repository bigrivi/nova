"""Prompt template builder."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from nova.settings import get_settings

DEFAULT_AGENT_IDENTITY = (
    "You are Nova, a personal AI assistant and autonomous AI agent.\n"
    "You help the user complete a wide range of practical tasks.\n"
    "You can proactively use available tools to move work forward when that is useful and safe."
)


@dataclass
class PromptConfig:
    identity_content: str = ""
    soul_content: str = ""
    user_content: str = ""


class PromptBuilder:
    SYSTEM_PROMPT_TEMPLATE = """\
{identity}

# Working Style
- Be concise and direct.
- Prefer doing the work with tools instead of only describing it.
- Before calling a tool, briefly explain why the call is needed.
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

# Tool Usage
- Prefer tool usage when the required runtime fact is not already present in the prompt.
- Runtime path context is already provided below. Do not call bash `pwd` just to learn Nova's home or workspace.
- Only use bash `pwd` when the user explicitly asks for the shell process working directory.
- Skills are dynamic. Call `list_skills` when you need the current available skills from the runtime catalog.
- If the user asks to use a skill, asks what skills are available, mentions a likely skill name, or the task sounds like a reusable workflow, call `list_skills` early.
- Call `load_skill` only after you know the exact skill name and need the full `SKILL.md`.
- If `list_skills` shows a relevant match, call `load_skill` before doing the workflow from memory.
- Only call `install_skill` when the user explicitly asks you to install a ClawHub skill.
- If you are unsure whether a skill is already installed locally, call `list_skills` before `install_skill`.
- If the skill is already installed and the user did not ask to update or replace it, prefer `load_skill` instead of reinstalling.

# Current Available Skills
{available_skills}

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
        available_skills: list[Any] | None = None,
    ) -> str:
        parts = []
        settings = get_settings()

        tools_section = self._build_tools_section(
            tools_schemas) if tools_schemas else ""
        available_skills_section = self._build_available_skills_section(available_skills)

        identity = self.config.identity_content or DEFAULT_AGENT_IDENTITY
        parts.append(self.SYSTEM_PROMPT_TEMPLATE.format(
            identity=identity,
            tools=tools_section,
            available_skills=available_skills_section,
            date=datetime.now().strftime("%Y-%m-%d %A"),
            home=settings.home,
            workspace_dir=settings.workspace_dir,
            platform=self._get_platform(),
        ))

        if self.config.soul_content:
            parts.append(f"## Soul\n\n{self.config.soul_content}")

        if self.config.user_content:
            parts.append(f"## User\n\n{self.config.user_content}")

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

    def _build_available_skills_section(self, available_skills: list[Any] | None) -> str:
        if not available_skills:
            return "- No skills currently installed in the runtime catalog."

        lines = []
        for skill in available_skills:
            name = str(getattr(skill, "name", "") or "").strip() or "unknown-skill"
            description = str(getattr(skill, "description", "") or "").strip() or "(no description)"
            lines.append(f"- {name}: {description}")
        lines.append("- If one of these matches the task, call `load_skill` with the exact skill name before using it.")
        return "\n".join(lines)

def build_system_prompt(
    tools_schemas: list[dict] = None,
    config: PromptConfig = None,
    available_skills: list[Any] | None = None,
) -> str:
    builder = PromptBuilder(config)
    return builder.build(tools_schemas, available_skills)
