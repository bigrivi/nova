"""Truncated write diffs must stay parseable.

The write tool caps how much diff it returns to the model. Cutting inside a hunk
leaves the header promising more lines than the body has, which diff parsers
reject. `truncate_diff` drops the partial hunk instead.
"""

from __future__ import annotations

import re

from nova.tools.write import truncate_diff

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
MARKER = re.compile(r"^\[\.\.\. \d+ more lines \.\.\.\]$")


def _hunk_lines(diff_lines: list[str]) -> list[list[str]]:
    hunks: list[list[str]] = []
    current: list[str] | None = None
    for line in diff_lines:
        if line.startswith("@@"):
            current = [line]
            hunks.append(current)
        elif current is not None:
            current.append(line)
    return hunks


def _counts(hunk: list[str]) -> tuple[int, int, int, int]:
    match = HUNK.match(hunk[0])
    assert match is not None
    old_expected = int(match.group(2) or 1)
    new_expected = int(match.group(4) or 1)
    old_seen = new_seen = 0
    for line in hunk[1:]:
        prefix = line[:1]
        if prefix == "+":
            new_seen += 1
        elif prefix == "-":
            old_seen += 1
        elif prefix in (" ", ""):
            old_seen += 1
            new_seen += 1
    return old_expected, old_seen, new_expected, new_seen


def _diff() -> list[str]:
    return [
        "--- a/x.py\n",
        "+++ b/x.py\n",
        "@@ -1,3 +1,3 @@\n",
        " one\n",
        "-two\n",
        "+TWO\n",
        " three\n",
        "@@ -20,3 +20,3 @@\n",
        " twenty\n",
        "-twentyone\n",
        "+TWENTYONE\n",
        " twentytwo\n",
        "@@ -40,3 +40,3 @@\n",
        " forty\n",
        "-fortyone\n",
        "+FORTYONE\n",
        " fortytwo\n",
    ]


def test_truncated_diff_keeps_only_complete_hunks() -> None:
    shown, remaining = truncate_diff(_diff(), limit=8)

    assert remaining > 0
    assert sum(1 for line in shown if line.startswith("@@")) == 1
    for hunk in _hunk_lines(shown):
        old_expected, old_seen, new_expected, new_seen = _counts(hunk)
        assert old_expected == old_seen
        assert new_expected == new_seen


def test_first_hunk_is_kept_even_when_over_the_limit() -> None:
    shown, remaining = truncate_diff(_diff(), limit=1)

    assert sum(1 for line in shown if line.startswith("@@")) == 1
    assert remaining == len(_diff()) - len(shown)


def test_no_truncation_reports_zero_remaining() -> None:
    lines = _diff()
    shown, remaining = truncate_diff(lines, limit=len(lines))

    assert shown == lines
    assert remaining == 0


def test_remaining_matches_omitted_lines() -> None:
    lines = _diff()
    shown, remaining = truncate_diff(lines, limit=8)

    assert len(shown) + remaining == len(lines)
