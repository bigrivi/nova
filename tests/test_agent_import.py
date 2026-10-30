"""Parsing opencode-style agent Markdown into Nova's agent model."""

from __future__ import annotations

import pytest

from nova.config.agent_import import (
    AgentImportError,
    parse_agent_markdown,
    slugify_key,
)

SAMPLE = """\
---
description: Expert visual designer specializing in creating intuitive, beautiful,
  and accessible user interfaces. Masters design systems and interaction patterns.
mode: subagent
tools:
  write: true
  edit: true
  bash: true
temperature: 0.55
steps: 20
---

You are a senior UI designer.

## Execution Flow
Do great work.
"""


def test_parses_frontmatter_and_body() -> None:
    parsed = parse_agent_markdown(SAMPLE)
    assert parsed.mode == "subagent"
    assert parsed.description.startswith("Expert visual designer")
    assert "accessible user interfaces" in parsed.description  # folded line joined
    assert parsed.tools == {"write": True, "edit": True, "bash": True}
    assert parsed.body.startswith("You are a senior UI designer.")
    assert "## Execution Flow" in parsed.body


def test_write_tools_map_to_full_posture() -> None:
    assert parse_agent_markdown(SAMPLE).posture == "full"


def test_read_only_when_no_write_tools() -> None:
    content = "---\nmode: subagent\ntools:\n  read: true\n  grep: true\n---\nBody.\n"
    assert parse_agent_markdown(content).posture == "read_only"


def test_unsupported_fields_reported_as_warnings() -> None:
    warnings = parse_agent_markdown(SAMPLE).warnings
    assert any("temperature" in warning for warning in warnings)
    assert any("steps" in warning for warning in warnings)


def test_missing_frontmatter_raises() -> None:
    with pytest.raises(AgentImportError):
        parse_agent_markdown("# just markdown, no frontmatter\n")


def test_defaults_when_minimal() -> None:
    parsed = parse_agent_markdown("---\ndescription: hi\n---\nBody\n")
    assert parsed.mode == "primary"  # default
    assert parsed.posture == "read_only"  # no write-capable tools
    assert parsed.model == ""
    assert parsed.provider == ""


def test_parses_optional_name_field() -> None:
    parsed = parse_agent_markdown(
        "---\nname: UI Designer\nmode: subagent\n---\nBody.\n"
    )
    assert parsed.name == "UI Designer"


def test_slugify_key() -> None:
    assert slugify_key("UI Designer") == "ui-designer"
    assert slugify_key("  Data/Analyst!! ") == "data-analyst"


# ── the Claude Code / Cursor dialect ─────────────────────────────────


def test_comma_tool_allowlist_without_a_writer_is_read_only() -> None:
    parsed = parse_agent_markdown(
        "---\nname: Reviewer\ndescription: d\ntools: Read, Grep, Glob\n---\nB.\n"
    )
    assert parsed.name == "Reviewer"
    assert parsed.posture == "read_only"
    assert parsed.tools == {"Read": True, "Grep": True, "Glob": True}


def test_comma_tool_allowlist_with_bash_is_full() -> None:
    parsed = parse_agent_markdown(
        "---\ndescription: d\ntools: Read, Bash(git push *)\n---\nB.\n"
    )
    assert parsed.posture == "full", "the specifier still names the bash tool"


def test_disallowed_tools_subtract_from_the_allowlist() -> None:
    parsed = parse_agent_markdown(
        "---\ndescription: d\ntools: Read, Bash\ndisallowedTools: Bash\n---\nB.\n"
    )
    assert parsed.posture == "read_only"


def test_an_explicit_permission_grant_is_the_only_way_to_full() -> None:
    granted = parse_agent_markdown(
        "---\ndescription: d\npermission:\n  edit: allow\n---\nB.\n"
    )
    denied = parse_agent_markdown(
        "---\ndescription: d\npermission:\n  edit: deny\n  bash: deny\n---\nB.\n"
    )
    assert granted.posture == "full"
    assert denied.posture == "read_only"


def test_an_ask_permission_is_not_a_grant() -> None:
    parsed = parse_agent_markdown(
        "---\ndescription: d\npermission:\n  bash: ask\n---\nB.\n"
    )
    assert parsed.posture == "read_only", "an approval prompt is not a grant"


def test_a_provider_model_reference_is_split() -> None:
    parsed = parse_agent_markdown(
        "---\ndescription: d\nmodel: opencode-go/deepseek-v4.1-flash\n---\nB.\n"
    )
    assert (parsed.provider, parsed.model) == ("opencode-go", "deepseek-v4.1-flash")


def test_a_model_alias_is_left_without_a_provider() -> None:
    """Guessing a provider would point the agent at a model that does not exist."""
    parsed = parse_agent_markdown("---\ndescription: d\nmodel: sonnet\n---\nB.\n")
    assert parsed.model == "sonnet"
    assert parsed.provider == ""


def test_mode_all_is_treated_as_primary() -> None:
    parsed = parse_agent_markdown("---\ndescription: d\nmode: all\n---\nB.\n")
    assert parsed.mode == "primary"
    assert not any("mode" in warning for warning in parsed.warnings)


def test_invalid_yaml_is_rejected_with_a_parse_error() -> None:
    with pytest.raises(AgentImportError, match="valid YAML"):
        parse_agent_markdown("---\ndescription: [unclosed\n---\nB.\n")
