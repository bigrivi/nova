"""The read-only proof that gates `plan` mode's shell tool.

Two properties carry the weight, and each is a way the change could have been
wrong in the dangerous direction:

* The refusals still refuse. Only `cd` and `git -C <dir>` were added; a
  redirect, a substitution, a writer, and every other git global flag must stay
  refused, because a false allow here is a read-only agent that writes.
* The refusal names the offending segment. A reason that says "this command" for
  a five-segment chain sends the model guessing, and each guess is a wasted
  turn.
"""

from __future__ import annotations

import pytest

from nova.tools.shell.readonly import is_read_only_command, unprovable_segment

WORKSPACE = "/Users/andy/Workspace/codes/ai/nova"


@pytest.mark.parametrize(
    "command",
    [
        # The shape that started this: the model explores relative to a path.
        f"cd {WORKSPACE} && git log --oneline -20 && cat pyproject.toml",
        f"cd {WORKSPACE} && ls -la",
        # `-C` only chooses the directory, and the subcommand is a reader.
        f"git -C {WORKSPACE} log --oneline -20",
        f"git -C {WORKSPACE} status --short",
        "git log --oneline -20",
    ],
)
def test_provable_commands_are_allowed(command: str) -> None:
    assert is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        # A writer anywhere in the chain refuses the whole line, `cd` or not.
        f"cd {WORKSPACE} && rm -rf build",
        f"git -C {WORKSPACE} checkout main",
        # `-c` can define an alias that runs a shell; that is why no global
        # flag other than -C is accepted.
        "git -c alias.x='!rm -rf /' x",
        "git --git-dir=/tmp/x log",
        "cat pyproject.toml > out.txt",
        "cat $(printf f)",
        "cat `${printf f}`",
        "python3 -c 'print(1)'",
        "sudo ls",
        "find . -name '*.tmp' -delete",
    ],
)
def test_unprovable_commands_are_refused(command: str) -> None:
    assert is_read_only_command(command) is False


def test_the_refusal_names_the_segment_not_the_whole_line() -> None:
    command = f"cd {WORKSPACE} && git log --oneline -20 && rm -rf build"

    assert unprovable_segment(command) == "rm -rf build"


def test_a_clean_line_has_no_offender() -> None:
    assert unprovable_segment(f"cd {WORKSPACE} && cat pyproject.toml") is None


def test_a_redirection_is_blamed_on_the_line_that_carries_it() -> None:
    """No single command is at fault: the redirect is written outside them."""
    command = "cat pyproject.toml > out.txt"

    assert unprovable_segment(command) == command


@pytest.mark.asyncio
async def test_the_reason_the_model_receives_names_the_segment() -> None:
    """The wiring, not just the prover: this text is what reaches the model."""
    from nova.tools.approval import ApprovalManager
    from nova.tools.behavior import ShellToolBehavior, TurnContext

    behavior = ShellToolBehavior(ApprovalManager(), shell_read_only=True)
    check = await behavior.before_execute(
        {"command": f"cd {WORKSPACE} && rm -rf build", "description": "clean"},
        TurnContext(),
    )

    assert check.allowed is False
    assert "`rm -rf build`" in (check.reject_reason or "")
