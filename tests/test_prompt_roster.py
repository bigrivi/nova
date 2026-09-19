"""System prompt surfaces the delegatable sub-agent roster."""

from __future__ import annotations

from nova.prompt.builder import PromptBuilder, PromptConfig


def test_roster_rendered_when_present() -> None:
    config = PromptConfig(
        subagent_roster="- `researcher` (read-only): investigate\n- `coder` (full access): implement"
    )
    prompt = PromptBuilder(config).build(tools_schemas=[])

    assert "## Available Sub-Agents" in prompt
    assert "delegate_to_agent(target=<key>" in prompt
    assert "`researcher` (read-only): investigate" in prompt
    assert "`coder` (full access): implement" in prompt


def test_no_roster_section_when_empty() -> None:
    prompt = PromptBuilder(PromptConfig()).build(tools_schemas=[])
    assert "## Available Sub-Agents" not in prompt
