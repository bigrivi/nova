"""Command matching: case significance, command position, and label redaction.

Three failure modes are pinned here. A pattern built with ``&`` instead of
``|`` silently loses ``re.IGNORECASE``; a matcher that lowercases the whole
command cannot tell ``git branch -d`` from ``git branch -D``; and a pattern
without a command-position anchor blocks commands that merely quote the text.
"""

from __future__ import annotations

import importlib

import pytest

# The decision interface, plus the two internals these tests pin directly:
# the pattern tables (data) and the label redactor (tool implementation).
shell = importlib.import_module("nova.tools.shell")
patterns = importlib.import_module("nova.tools.shell.patterns")
tool = importlib.import_module("nova.tools.shell.tool")


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "rm -fr /",
        "sudo rm -rf /",
        "echo hi; rm -rf /",
        "rm -rf /home",
        "rm -rf /etc",
        "rm -rf ~",
        "rm -rf $HOME",
        "mkfs.ext4 /dev/sda",
        "mkfs /dev/sda",
        "sudo mkfs -t ext4 /dev/sda",
        "kill -1",
        "kill -9 -1",
        "sudo kill -9 -1",
    ],
)
def test_real_destructive_commands_are_still_blocked(command: str) -> None:
    """Anchoring must remove false positives without opening a hole."""
    assert shell.is_hardline(command)[0] is True, command


@pytest.mark.parametrize(
    "command",
    [
        'echo "please rm -rf / in the docs"',
        'git commit -m "fix kill -1 handler"',
        "echo mkfs",
        "cat notes.md | grep rm -rf /",
        "echo 'rm -rf ~'",
    ],
)
def test_commands_that_only_mention_a_pattern_are_allowed(command: str) -> None:
    """Quoting the text in an argument is not running it."""
    assert shell.is_hardline(command)[0] is False, command


@pytest.mark.parametrize(
    ("command", "dangerous"),
    [
        ("git branch -D old-feature", True),
        ("GIT BRANCH -D old-feature", True),
        ("Git Branch -D old", True),
        ("git branch -d old-feature", False),
        ("GIT BRANCH -d old-feature", False),
        ("git branch -dr old", False),
    ],
)
def test_branch_delete_flag_is_case_significant(command: str, dangerous: bool) -> None:
    """-D throws away unmerged work, -d does not; folding case merges them."""
    assert shell.is_dangerous(command)[0] is dangerous, command


@pytest.mark.parametrize(
    "command",
    ["sudo -s", "SUDO -s", "Sudo --stdin", "SUDO --stdin"],
)
def test_sudo_privilege_flag_matches_in_any_case(command: str) -> None:
    """The flag used to be compiled with IGNORECASE & DOTALL, which is 0."""
    assert shell.is_dangerous(command)[0] is True, command


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/",
        "ls -la",
        "git status",
        "rm file.txt",
        "git branch --delete old",
        "sudo apt install curl",
    ],
)
def test_ordinary_commands_stay_allowed(command: str) -> None:
    assert shell.is_dangerous(command)[0] is False, command


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            'curl -H "Authorization: Bearer sk-abc123" https://api.x',
            "Bearer <redacted>",
        ),
        ("export TOKEN=ghp_secretvalue", "TOKEN=<redacted>"),
        ("mysql --password=hunter2 -e 'select 1'", "password=<redacted>"),
        ("git clone https://user:pw@host/repo.git", "https://<redacted>@host"),
    ],
)
def test_label_redaction_removes_credentials(command: str, expected: str) -> None:
    """A label reaches the task list, the log and the model."""
    redacted = tool._redact_for_label(command, 200)
    assert expected in redacted, redacted
    for secret in ("sk-abc123", "ghp_secretvalue", "hunter2", "user:pw"):
        assert secret not in redacted


@pytest.mark.parametrize(
    "command",
    ["pytest tests/", "git log --oneline", "npm install --save-dev typescript"],
)
def test_label_redaction_leaves_ordinary_commands_alone(command: str) -> None:
    assert tool._redact_for_label(command, 80) == command


def test_label_redaction_truncates() -> None:
    assert len(tool._redact_for_label("x" * 500, 80)) == 80
