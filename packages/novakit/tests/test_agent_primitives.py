"""Tests for agent primitives that do not require the Nova application."""

from novakit.agent import GuardrailAction, ToolGuardrails, TurnState


def test_turn_state_defaults_are_per_instance() -> None:
    first = TurnState()
    second = TurnState()

    first.workspace = "/workspace"
    first.overflow_recovered = True

    assert second.workspace is None
    assert second.overflow_recovered is False


def test_guardrails_halt_repeated_identical_calls() -> None:
    guardrails = ToolGuardrails(max_same_call=2)

    assert guardrails.observe("shell", {"command": "pwd"}, True) is (
        GuardrailAction.ALLOW
    )
    assert guardrails.observe("shell", {"command": "pwd"}, True) is (
        GuardrailAction.ALLOW
    )
    assert guardrails.observe("shell", {"command": "pwd"}, True) is (
        GuardrailAction.HALT
    )


def test_guardrails_allow_custom_read_tool_names() -> None:
    guardrails = ToolGuardrails(
        max_no_write_reads=1,
        read_tools=frozenset({"inspect"}),
    )

    assert guardrails.observe("inspect", {"path": "a"}, True) is GuardrailAction.ALLOW
    assert guardrails.observe("inspect", {"path": "b"}, True) is GuardrailAction.WARN


def test_guardrails_warn_after_too_many_reads_and_reset() -> None:
    guardrails = ToolGuardrails(max_no_write_reads=2)

    assert guardrails.observe("read", {"path": "a"}, True) is GuardrailAction.ALLOW
    assert guardrails.observe("read", {"path": "b"}, True) is GuardrailAction.ALLOW
    assert guardrails.observe("read", {"path": "c"}, True) is GuardrailAction.WARN

    guardrails.reset()

    assert guardrails.observe("read", {"path": "d"}, True) is GuardrailAction.ALLOW
