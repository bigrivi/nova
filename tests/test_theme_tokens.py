"""Theme token contract for the frontend stylesheet.

A theme is a class that sets the same custom properties as ``.dark``; adding
one should mean copying a block, not editing components. These tests fail when
the blocks drift, which is what would silently leave a new theme with the wrong
colours or the wrong sidebar type scale.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

INDEX_CSS = (
    Path(__file__).resolve().parent.parent / "frontend" / "src" / "index.css"
)

# Tokens a theme overrides to change presentation (weight, size, spacing,
# shadow, scrollbars) rather than colour.
PRESENTATION_TOKENS = (
    "--sidebar-title-size",
    "--sidebar-title-weight",
    "--sidebar-section-size",
    "--sidebar-section-weight",
    "--sidebar-date-size",
    "--sidebar-date-weight",
    "--sidebar-project-weight",
    "--sidebar-gutter",
    "--sidebar-section-radius",
    "--composer-disclaimer-size",
    "--composer-shadow",
    "--placeholder-text",
    "--code-block-fg",
    "--scrollbar-size",
    "--scrollbar-thumb",
    "--scrollbar-thumb-hover",
)


def _block_properties(selector: str) -> list[str]:
    """Return the custom properties declared inside a CSS block."""
    css = INDEX_CSS.read_text(encoding="utf-8")
    match = re.search(
        rf"(?:^|\n){re.escape(selector)}\s*\{{([^}}]*)\}}", css
    )
    if match is None:
        raise AssertionError(f"theme block {selector} not found in index.css")
    return re.findall(r"^\s*(--[a-z0-9-]+)\s*:", match.group(1), re.MULTILINE)


def test_dark_theme_only_redefines_existing_tokens() -> None:
    """A theme may inherit a value, but not invent a token."""
    root = set(_block_properties(":root"))
    dark = _block_properties(".dark")

    assert [name for name in dark if name not in root] == []


def test_presentation_tokens_are_overridable() -> None:
    known = set(_block_properties(":root")) | set(_block_properties(".dark"))

    missing = [token for token in PRESENTATION_TOKENS if token not in known]
    assert missing == []


def test_components_do_not_branch_on_theme_for_presentation() -> None:
    """No component should carry a ``dark:`` variant for weight/size/spacing.

    Colour variants are allowed (the shadcn primitives ship their own); the
    presentation tokens exist precisely so these do not accumulate.
    """
    components = (INDEX_CSS.parent).rglob("*.tsx")
    offenders: list[str] = []
    banned = (
        "dark:text-xs",
        "dark:text-sm",
        "dark:font-medium",
        "dark:font-semibold",
        "dark:px-",
        "dark:py-",
        "dark:rounded",
        "dark:shadow",
    )
    for path in components:
        if "components/ui/" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        offenders.extend(
            f"{path.name}: {variant}"
            for variant in banned
            if variant in text
        )

    assert offenders == []


@pytest.mark.parametrize("selector", [":root", ".dark"])
def test_cheap_guard_that_blocks_are_parsable(selector: str) -> None:
    """The blocks above must actually declare colour tokens."""
    assert len(_block_properties(selector)) > 20


def test_base_layer_declares_an_interactive_cursor() -> None:
    """Controls must say they are clickable; the UA stylesheet does not.

    The browser only defaults ``<a href>`` to a pointer, so without this rule
    every button shows an arrow. It must stay in ``@layer base``: utilities
    outrank that layer, which is what preserves the deliberate
    ``cursor-default`` on menu items and read-only chips.
    """
    css = INDEX_CSS.read_text(encoding="utf-8")
    base = re.search(r"@layer base\s*\{(.*?)\n\}", css, re.DOTALL)
    assert base is not None, "@layer base block not found in index.css"
    body = base.group(1)

    assert re.search(r"button:not\(:disabled\)", body), (
        "base layer must make enabled buttons show a pointer")
    assert "@apply cursor-pointer" in body
    # Utilities must keep winning, or read-only chips would start lying.
    assert re.search(r"@layer utilities", css) or "cursor-default" in css
