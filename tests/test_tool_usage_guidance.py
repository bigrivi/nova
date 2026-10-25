"""Tool-usage guidance: `edit` is the default for existing files, `write` is new-only.

The model picks between the two tools on its own, so both the system prompt and
the tool descriptions have to agree on the precedence. A soft rule cannot force
it, but contradictory descriptions made `write` look like a normal way to
overwrite an existing file.
"""

from __future__ import annotations

import nova.tools.edit  # noqa: F401  (registers the tool metadata)
import nova.tools.write  # noqa: F401
from nova.prompt.builder import PromptBuilder, PromptConfig
from nova.tools.registry import _tool_metadata


def test_prompt_prefers_edit_for_existing_files() -> None:
    prompt = PromptBuilder(PromptConfig()).build()

    assert "`edit` changes existing files" in prompt
    assert "`write` only creates new ones" in prompt


def test_edit_description_covers_whole_file_rewrites() -> None:
    description = _tool_metadata["edit"]["description"]

    assert "existing file" in description
    assert "Default for any change" in description
    assert "whole-file rewrites" in description


def test_write_description_is_new_files_only() -> None:
    description = _tool_metadata["write"]["description"]

    assert "Create a new file only" in description
    assert "Use edit" in description
