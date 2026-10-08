"""The grant family has to be stable under variation and narrow enough to matter.

Both halves are easy to get wrong and neither shows up in ordinary use. Too wide
(`git` for everything git) makes a remembered approval cover a sibling the user
never saw. Too narrow (the whole command line) makes it inert, because an agent
interpolates a URL and never repeats itself -- which is why the original code
keyed grants on the rule at all.

The table is the part that cannot be derived, so the cases below are the
conventions the arity encodes, one per shape.
"""

from __future__ import annotations

import pytest

from nova.tools.shell.arity import command_family


class TestNarrowEnough:
    """A remembered approval must not cover a sibling command."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            # Arity counts the words that make the command's name, so
            # `docker compose` is three words and `docker` is two. That is why
            # compose subcommands and plain docker subcommands land in different
            # families rather than both under `docker *`.
            ("docker compose restart api", "docker compose restart *"),
            ("docker restart web", "docker restart *"),
            # A subcommand that takes an argument of its own.
            ("git checkout main", "git checkout *"),
            ("git push origin main", "git push *"),
            # Tools whose second word is a mode or a path, not a subcommand.
            ("chmod 755 script.sh", "chmod *"),
            ("cp ./a.txt b.txt", "cp *"),
            ("npm run dev", "npm run dev *"),
            ("npm install", "npm install *"),
        ],
    )
    def test_family(self, command: str, expected: str) -> None:
        assert command_family(command) == expected, command

    def test_two_git_subcommands_do_not_share_a_family(self) -> None:
        """The case the rule-only grant got wrong.

        `git push` is the destructive one and `git checkout` is not, so approving
        the first must not authorise the second.
        """
        assert command_family("git push --force origin main") == "git push *"
        assert command_family("git checkout -b feature") == "git checkout *"

    def test_a_docker_subcommand_does_not_carry_the_compose_family(self) -> None:
        """`docker compose restart` and `docker restart` are different commands.

        Both start with `docker`, and one of them tears down a compose stack. The
        family has to say which.
        """
        assert (
            command_family("docker compose restart api") == "docker compose restart *"
        )
        assert command_family("docker restart web") == "docker restart *"

    def test_shutdown_variants_are_separate_families(self) -> None:
        """Four programs the rule treats as one decision, four families.

        A user who allowed `reboot` in a script should not thereby allow
        `poweroff`.
        """
        families = {
            command_family(cmd)
            for cmd in (
                "sudo reboot",
                "sudo halt",
                "sudo poweroff",
                "sudo shutdown -h now",
            )
        }
        assert len(families) == 4, families


class TestStableUnderVariation:
    """The reason grants are not keyed on the command text."""

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            ("curl -s https://a.example/1", "curl -s https://b.example/2"),
            (
                "python3 -c \"json.load(open('/tmp/a'))\"",
                "python3 -c \"json.load(open('/var/tmp/b'))\"",
            ),
            ("git push --force origin main", "git push --force origin release"),
            ("rm -rf /tmp/build-1", "rm -rf /tmp/build-2"),
        ],
    )
    def test_variation_keeps_the_family(self, first: str, second: str) -> None:
        assert command_family(first) == command_family(second), (first, second)


class TestFallbacks:
    def test_an_unknown_program_is_its_first_word(self) -> None:
        assert command_family("weirdtool --flag value") == "weirdtool *"

    def test_a_wrapper_is_not_part_of_the_family(self) -> None:
        assert command_family("sudo git push --force") == "git push *"
        assert command_family("env FOO=1 python3 app.py") == "python3 *"
        assert command_family("nohup npm run dev") == "npm run dev *"

    def test_a_quoted_span_is_one_word(self) -> None:
        """A script is one argument however much whitespace it contains."""
        assert command_family('python3 -c "import sys; print(sys.argv)"') == "python3 *"

    def test_no_words_is_no_family(self) -> None:
        """Empty means "cannot be named", and the caller must not read it as a
        family matching everything."""
        assert command_family("") == ""
        assert command_family("   ") == ""
