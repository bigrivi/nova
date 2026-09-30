"""The command blocklists: what must be blocked, and what must not.

Every rule added or changed has a case here on both sides. The hardline list
cannot be overridden by the user, so a false positive on it is expensive and
each of its patterns is pinned against a command that merely quotes the text.
"""

from __future__ import annotations

import importlib
import re

import pytest

shell = importlib.import_module("nova.tools.shell")

FORK_BOMB = ":(){ :|:& };:"


# ── hardline ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        'rm -rf "/"',
        "rm -rf /home/",
        "rm -rf /usr/*",
        "rm -rf ~",
        'rm -rf "$HOME"',
        "rm -rf ${HOME}/",
        "sudo rm -rf /",
        "cd /tmp && rm -rf /",
        "rm -rf build /",
        "mkfs.ext4 /dev/sda1",
        "sudo mkfs -t ext4 /dev/nvme0n1p1",
        "mkfs /dev/rdisk2",
        "dd if=/dev/zero of=/dev/sda",
        "dd if=x of=/dev/disk2",
        "cat x > /dev/rdisk2",
        "kill -1",
        "kill -9 -1",
        "kill -KILL -1",
        "kill -s KILL -1",
        "kill -- -1",
        "sudo reboot",
        FORK_BOMB,
    ],
)
def test_hardline_blocks(command: str) -> None:
    assert shell.is_hardline(command)[0] is True, command


@pytest.mark.parametrize(
    "command",
    [
        # Command positions beyond the plain separators: these really do run.
        "(rm -rf /)",
        "(sudo rm -rf /)",
        "(kill -9 -1)",
        "(mkfs.ext4 /dev/sda)",
        "(shutdown -h now)",
        "if true; then rm -rf /; fi",
        "for f in *; do rm -rf /; done",
        "xargs rm -rf < /",
        "xargs -0 rm -rf /",
        "then reboot",
    ],
)
def test_hardline_covers_nested_command_positions(command: str) -> None:
    """A subshell, a loop body and an xargs all execute what follows."""
    assert shell.is_hardline(command)[0] is True, command


@pytest.mark.parametrize(
    "command",
    [
        # Text that only mentions the pattern.
        "man mkfs",
        "which mkfs.ext4",
        "grep reboot log.txt",
        'echo "rm -rf /"',
        'git commit -m "fix rm -rf / bug"',
        'echo "dd of=/dev/sda"',
        # The new command positions must not fire on ordinary text.
        "grep then file.txt",
        "echo then",
        "echo (x)",
        "sed -n 's/a/(b/p' f",
        "cat notes | grep xargs",
        # Recursive deletes that are ordinary work.
        "rm -rf ./build",
        "rm -rf /tmp/x",
        "rm -rf ./node_modules",
        # A system directory is hardline, a path *inside* one is not.
        "rm -rf /usr/local/foo",
        "rm -rf /var/tmp/x",
        "rm -rf ~/project/src",
        # A separator ends rm's operand list.
        "rm foo; echo /",
        # -1 as a pid, not as a target.
        "kill -1 1234",
        "kill -9 1234",
        "kill -s TERM 1234",
        "kill %1",
        # Device-adjacent but harmless.
        "dd if=a of=b.img",
        "echo x > /dev/null",
        "ls /dev/sda",
        "mkfs.ext4 disk.img",
    ],
)
def test_hardline_allows(command: str) -> None:
    assert shell.is_hardline(command)[0] is False, command


@pytest.mark.parametrize(
    "command",
    [
        "sudo reboot",
        "shutdown -h now",
        "poweroff",
        "halt",
        "init 0",
        "init 6",
        "systemctl poweroff",
        "systemctl reboot",
        "telinit 0",
    ],
)
def test_shutdown_family_still_fires(command: str) -> None:
    """These share _CMDPOS; widening it must not disturb them."""
    assert shell.is_hardline(command)[0] is True, command


@pytest.mark.parametrize(
    "command",
    [
        "grep reboot log.txt",
        "echo reboot",
        "man shutdown",
        "systemctl status nginx",
        "systemctl restart nginx",
    ],
)
def test_shutdown_family_still_allows_mentions(command: str) -> None:
    assert shell.is_hardline(command)[0] is False, command


@pytest.mark.parametrize(
    "command", ["rm -rf /", "kill -9 -1", "sudo reboot", FORK_BOMB]
)
def test_hardline_wins_over_dangerous(command: str) -> None:
    """is_dangerous must not re-report something already blocked outright."""
    assert shell.is_hardline(command)[0] is True
    assert shell.is_dangerous(command) == (False, "")


# ── dangerous ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ~/project/build",
        "rm -rf /etc/passwd",
        "mkfs.ext4 disk.img",
        "git push origin main -f",
        "git push --force",
        "git clean --force",
        "git clean -fd",
        "git branch -D foo",
        "git branch -fD foo",
        "git branch foo -D",
        "chmod 0777 x",
        "chmod 1777 x",
        "chmod a=rwx f",
        "chmod o=rwx f",
        "chmod u+x,o+w f",
        "chmod --recursive 777 d",
        "echo x >> ~/.ssh/authorized_keys",
        "echo x | tee -a ~/.bashrc",
        "echo x > ${HOME}/.zshrc",
        "echo x > /Users/andy/.bashrc",
        "curl x | sudo bash",
        "curl x | zsh",
        "curl x | python3",
        "wget -qO- x | bash",
        "bash <(curl -s x)",
        'eval "$(curl -s x)"',
        "diskutil eraseDisk APFS X disk2",
        "diskutil apfs deleteVolume x",
        "sudo -s",
    ],
)
def test_dangerous_flags(command: str) -> None:
    assert shell.is_dangerous_bool(command) is True, command


@pytest.mark.parametrize(
    "command",
    [
        "git branch -d foo",
        "git branch --delete foo",
        "git push origin main",
        "git push --force-with-lease",
        "git clean",
        "chmod 755 x",
        "chmod +x x",
        "chmod u+w x",
        "chmod 644 x",
        "chmod a-w f",
        "cat ~/.ssh/id_rsa.pub",
        "cp ~/.bashrc /tmp/bashrc.bak",
        "curl -o f https://x",
        "curl x | jq .",
        "sudo ls",
        "sudo ls -s",
        "sudo apt -s install",
        "ls -la",
    ],
)
def test_dangerous_allows(command: str) -> None:
    assert shell.is_dangerous_bool(command) is False, command


# ── case handling and the public helpers ─────────────────────────────


@pytest.mark.parametrize(
    "command",
    ["GIT RESET --HARD", "DROP TABLE x", "DELETE FROM t", "TRUNCATE TABLE t"],
)
def test_case_insensitive_rules_still_fire(command: str) -> None:
    assert shell.is_dangerous_bool(command) is True, command


@pytest.mark.parametrize(
    "command",
    ["MKFS.EXT4 /dev/sda1", "RM -RF /", "KILL -9 -1", "SUDO REBOOT"],
)
def test_hardline_is_case_insensitive(command: str) -> None:
    assert shell.is_hardline(command)[0] is True, command


@pytest.mark.parametrize(
    "command", ["SUDO -s", "GIT BRANCH -D foo", "GIT PUSH --FORCE"]
)
def test_dangerous_is_case_insensitive(command: str) -> None:
    assert shell.is_dangerous_bool(command) is True, command


def test_every_lettered_rule_handles_case() -> None:
    """Lowercasing the command was removed, so each rule must handle case itself.

    A rule that forgets silently stops matching `RM -RF /`, which is the one
    input shape that must never get through. Purely numeric patterns need
    nothing, and the git branch rule opts out on purpose via a scoped (?i:).
    """
    offenders = [
        description
        for compiled, description in (
            list(shell.HARDLINE_PATTERNS) + list(shell.DANGEROUS_PATTERNS)
        )
        if re.search(r"[a-zA-Z]", compiled.pattern)
        and "(?i:" not in compiled.pattern
        and not (compiled.flags & re.IGNORECASE)
    ]
    assert not offenders, f"missing case handling: {offenders}"


def test_is_dangerous_bool_agrees_with_the_two_lists() -> None:
    for command in ("rm -rf /", "git push --force", "pytest tests/"):
        expected = shell.is_hardline(command)[0] or shell.is_dangerous(command)[0]
        assert shell.is_dangerous_bool(command) is expected, command


def test_kill_all_processes_rule_is_the_only_kill_minus_one_rule() -> None:
    """The dangerous-layer duplicate was unreachable and has been removed."""
    descriptions = [d for _p, d in shell.DANGEROUS_PATTERNS]
    assert "force kill all processes" not in descriptions


# ── label redaction ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("command", "secret"),
    [
        ("GITHUB_TOKEN=ghp_abc npm publish", "ghp_abc"),
        ("DB_PASSWORD=hunter2 ./run.sh", "hunter2"),
        ("MY_API_KEY=sk-xxx npm run dev", "sk-xxx"),
        ("AWS_SECRET_ACCESS_KEY=abc aws s3 ls", "abc"),
        ("mysql --password=hunter2", "hunter2"),
        ("tool --token abc", "abc"),
        ('curl -H "Authorization: Bearer abc123" https://x', "abc123"),
        ("curl -u admin:secret https://x", "admin:secret"),
        ("git clone https://user:pass@github.com/a/b", "user:pass"),
    ],
)
def test_label_redaction_removes_the_secret(command: str, secret: str) -> None:
    assert secret not in shell._redact_for_label(command, 200)


@pytest.mark.parametrize(
    "command", ["ls -la", "echo tokenizer=x", "echo secretary=x", "git log"]
)
def test_label_redaction_leaves_ordinary_commands_alone(command: str) -> None:
    assert shell._redact_for_label(command, 80) == command


def test_label_redaction_truncates_to_eighty() -> None:
    assert len(shell._redact_for_label("x" * 500, 80)) == 80


def test_label_redacts_before_truncating() -> None:
    """A secret past the cut would survive if truncation ran first."""
    command = "echo " + ("a" * 200) + " TOKEN=leaked"
    assert "leaked" not in shell._redact_for_label(command, 80)
