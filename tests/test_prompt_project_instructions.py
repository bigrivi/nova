"""Project Instructions section rendering in the system prompt."""

from nova.prompt.builder import PromptBuilder, PromptConfig
from nova.prompt.project_instructions import ProjectInstructions


def build_with(instructions):
    return PromptBuilder(PromptConfig()).build(project_instructions=instructions)


def test_absent_by_default():
    prompt = PromptBuilder(PromptConfig()).build()
    assert "## Project Instructions" not in prompt


def test_section_sits_before_subagents_and_soul():
    config = PromptConfig(
        subagent_roster="- helper (full access): helps\n",
        soul_content="Be kind.\n",
    )
    prompt = PromptBuilder(config).build(
        project_instructions=ProjectInstructions(
            text="Use uv.\n", sources=["/repo/AGENTS.md"]
        )
    )
    project_at = prompt.index("## Project Instructions")
    assert project_at < prompt.index("## Available Sub-Agents")
    assert project_at < prompt.index("## Soul")
    assert "Use uv." in prompt


def test_sources_listed():
    prompt = build_with(
        ProjectInstructions(
            text="Use uv.\n",
            sources=["/home/u/.nova/AGENTS.md", "/repo/AGENTS.md"],
        )
    )
    assert "In effect from: /home/u/.nova/AGENTS.md, /repo/AGENTS.md" in prompt


def test_flagged_named_not_silent():
    prompt = build_with(
        ProjectInstructions(
            text="Use uv.\n",
            sources=["/repo/AGENTS.md"],
            flagged=["/repo/pkg/AGENTS.md (ignore_previous)"],
        )
    )
    assert (
        "Omitted as potential injection: /repo/pkg/AGENTS.md (ignore_previous)"
        in prompt
    )
    assert "Use uv." in prompt


def test_flagged_only_still_renders_section():
    prompt = build_with(
        ProjectInstructions(text="", flagged=["/repo/AGENTS.md (role_hijack)"])
    )
    assert "## Project Instructions" in prompt
    assert "Omitted as potential injection" in prompt
