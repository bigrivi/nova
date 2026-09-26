"""System prompt surfaces the delegatable sub-agent roster."""

from __future__ import annotations

from nova.prompt.builder import PromptBuilder, PromptConfig


def test_roster_rendered_when_present() -> None:
    config = PromptConfig(
        subagent_roster="- `researcher` (read-only): investigate\n- `coder` (full access): implement"
    )
    prompt = PromptBuilder(config).build()

    assert "## Available Sub-Agents" in prompt
    assert "delegate_to_agent(target=<key>" in prompt
    assert "`researcher` (read-only): investigate" in prompt
    assert "`coder` (full access): implement" in prompt


def test_no_roster_section_when_empty() -> None:
    prompt = PromptBuilder(PromptConfig()).build()
    assert "## Available Sub-Agents" not in prompt


def test_roster_preamble_names_no_specific_agents() -> None:
    """The roster preamble must not hardcode agent keys.

    Which sub-agents exist depends on user configuration; naming
    `explore`/`reviewer`/`planner` here would instruct the model to
    delegate to targets it may not own.
    """
    config = PromptConfig(
        subagent_roster="- `researcher` (read-only): investigate\n- `coder` (full access): implement"
    )
    prompt = PromptBuilder(config).build()

    assert "`explore`" not in prompt
    assert "`reviewer`" not in prompt
    assert "`planner`" not in prompt


def test_roster_preamble_treats_roster_as_source_of_truth() -> None:
    """The preamble must tell the model the roster below is the complete
    set of valid targets, so it never invents a delegation key."""
    config = PromptConfig(subagent_roster="- `coder` (full access): implement")
    prompt = PromptBuilder(config).build()

    assert "complete set" in prompt
    assert "never" in prompt and "invent" in prompt


def test_delegate_tool_description_names_no_specific_agents() -> None:
    """Same guarantee for the `delegate_to_agent` tool description, which
    the model also reads when deciding whether to delegate."""
    import nova.tools.delegate  # noqa: F401 — importing registers the tool metadata
    from nova.tools.registry import _tool_metadata

    description = _tool_metadata["delegate_to_agent"]["description"]

    assert "`explore`" not in description
    assert "`reviewer`" not in description
    assert "`planner`" not in description
    assert "Available Sub-Agents" in description
