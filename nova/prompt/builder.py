"""Prompt template builder."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from nova.tools.shell_utils import get_shell_label
from nova.tools.threat_patterns import has_threats
from nova.settings import get_settings

DEFAULT_AGENT_IDENTITY = (
    "You are Nova, a general-purpose personal AI assistant and autonomous agent.\n"
    "You help the user with a wide range of practical work: software development, "
    "debugging, and code review; running shell commands and scripts; reading, "
    "writing, and editing files; web research; managing plans and todos; "
    "operating structured memory; and discovering reusable skills.\n"
    "You work through the full loop yourself: understand the request, gather "
    "facts with tools, do the work, verify the result, and report concisely.\n"
    "You can proactively use available tools — including delegating "
    "self-contained work to sub-agents and running long work as background "
    "tasks — when that moves things forward safely.\n"
    "You stay within your permissions: never bypass approval for sensitive "
    "actions, never invent tool results or file contents, and ask for "
    "clarification when a request is ambiguous or risky.\n"
    "Verify your work with the project's own build, lint, and test commands "
    "before reporting it done; never claim success from reasoning alone.\n"
    "Avoid destructive or irreversible actions — discarding others' changes, "
    "force-pushing, or deleting data — without the user's explicit confirmation."
)


@dataclass
class PromptConfig:
    identity_content: str = ""
    soul_content: str = ""
    user_content: str = ""
    memory_content: str = ""
    memory_index: str = ""
    subagent_roster: str = ""
    workspace_dir: str = ""

    @classmethod
    def from_agent_dir(cls, agent_dir) -> "PromptConfig":
        """Load an agent's persona files from its directory.

        SOUL/IDENTITY/USER/MEMORY are optional; a missing file is an empty
        section rather than an error.
        """
        from pathlib import Path

        agent_dir = Path(agent_dir)

        def read(name: str, strip: bool = False) -> str:
            path = agent_dir / name
            if not path.exists():
                return ""
            text = path.read_text(encoding="utf-8")
            return text.strip() if strip else text

        return cls(
            identity_content=read("IDENTITY.md", strip=True),
            soul_content=read("SOUL.md"),
            user_content=read("USER.md"),
            memory_content=read("MEMORY.md"),
            workspace_dir=str(agent_dir),
        )


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

# Tool Usage
- Prefer tool usage when the required runtime fact is not already present in the prompt.
- Runtime path context is already provided below. Do not call bash `pwd` just to learn Nova's home or workspace.
- Only use bash `pwd` when the user explicitly asks for the shell process working directory.
- `{home}/MEMORY.md` is your long-term memory, auto-injected every session as `## Long-Term Memory`. Use `write` with that path to update facts, preferences, or decisions when they change. Keep it concise.
- Skills are dynamic. Call `list_skills` when you need the current available skills from the runtime catalog.
- If the user asks to use a skill, asks what skills are available, mentions a likely skill name, or the task sounds like a reusable workflow, call `list_skills` early.
- Call `load_skill` only after you know the exact skill name and need the full `SKILL.md`.
- If `list_skills` shows a relevant match, call `load_skill` before doing the workflow from memory.
- Only call `install_skill` when the user explicitly asks you to install a ClawHub skill.
- If you are unsure whether a skill is already installed locally, call `list_skills` before `install_skill`.
- If the skill is already installed and the user did not ask to update or replace it, prefer `load_skill` instead of reinstalling.
- When calling `shell` or `code_run`, always include a `description` that briefly explains what the command or code does in active voice.

# Memory
- Only call `search_memory` when the current question is directly related to past preferences, decisions, or facts. Never search memory for unrelated topics.
- When search results are not relevant to the current question, ignore them and answer normally.
- Use `save_memory` to store important information for future sessions.
- When saving memory, choose scope: 'user' for stable cross-session facts and preferences; 'project' for project-specific decisions; 'session' ONLY for temporary context that expires with this conversation. Never store temporary task progress or conversation copies as user or project memory.

# Current Available Skills
{available_skills}

# Environment
- Current date: {date}
- Home: {home}
- Workspace: {workspace_dir}
- Platform: {platform}
- Shell: {shell}
"""

    def __init__(self, config: Optional[PromptConfig] = None):
        self.config = config or PromptConfig()

    def build(
        self,
        available_skills: list[Any] | None = None,
        date: str | None = None,
        workspace_override: str | None = None,
    ) -> str:
        """Render the system prompt.

        Tool definitions are deliberately absent: they reach the model through the
        provider's structured ``tools`` field, and repeating them here only charged
        for them twice. For the same reason there is no "output JSON only"
        instruction - tool calls arrive as structured events, never as text.
        """
        parts = []
        settings = get_settings()

        available_skills_section = self._build_available_skills_section(available_skills)

        identity = self.config.identity_content or DEFAULT_AGENT_IDENTITY
        parts.append(self.SYSTEM_PROMPT_TEMPLATE.format(
            identity=identity,
            available_skills=available_skills_section,
            date=date or datetime.now().strftime("%Y-%m-%d %A"),
            home=settings.home,
            workspace_dir=workspace_override or self.config.workspace_dir or str(settings.workspace_dir),
            platform=self._get_platform(),
            shell=get_shell_label(),
        ))

        if self.config.subagent_roster:
            parts.append(
                "## Available Sub-Agents\n\n"
                "You can delegate a self-contained task to any of these via "
                "`delegate_to_agent(target=<key>, task=...)`. Each runs in the "
                "background and reports its result back to you as a later message — "
                "do not wait or poll. The list below is the complete set of "
                "delegation targets you own: only these keys are valid, never "
                "invent or guess another target. Each entry states its access "
                "level and what it is for — match the task to the entry whose "
                "description fits best, and put everything the sub-agent needs "
                "in `task` since it starts fresh with no memory of this "
                "conversation. Do trivial single-file work yourself.\n\n"
                f"{self.config.subagent_roster}"
            )

        if self.config.soul_content:
            parts.append(f"## Soul\n\n{self.config.soul_content}")

        if self.config.user_content:
            if has_threats(self.config.user_content):
                parts.append("## User\n\n[User profile omitted — content flagged as potential injection]")
            else:
                parts.append(f"## User\n\n{self.config.user_content}")

        if self.config.memory_index:
            if has_threats(self.config.memory_index):
                parts.append("## Memory Index\n\n[Index omitted — content flagged as potential injection]\n\nListed memories exist but may be unrelated to the current question. Only query and use them when the current topic is directly related.")
            else:
                parts.append(f"## Memory Index\n\n{self.config.memory_index}\n\nListed memories exist but may be unrelated to the current question. Only query and use them when the current topic is directly related.")

        if self.config.memory_content:
            if has_threats(self.config.memory_content):
                parts.append("## Long-Term Memory\n\n[Memory omitted — content flagged as potential injection]")
            else:
                parts.append(f"## Long-Term Memory\n\n{self.config.memory_content}")

        return "\n\n".join(parts)

    def _get_platform(self) -> str:
        import platform
        return platform.system()

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
