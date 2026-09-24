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
    parsed = parse_agent_markdown("---\nname: UI Designer\nmode: subagent\n---\nBody.\n")
    assert parsed.name == "UI Designer"


def test_slugify_key() -> None:
    assert slugify_key("UI Designer") == "ui-designer"
    assert slugify_key("  Data/Analyst!! ") == "data-analyst"
