"""The announced tool call must describe the same call the tool receives.

ask_user numbers a question whose ``id`` the model omitted, but that repair used
to reach the client only in the tool *result*. The *announcement* -- the copy a
client renders while the turn is paused waiting for an answer -- still carried
the model's original, id-less questions, so the two frames described one call
differently and an answer could not be mapped back to its question.

These tests pin the invariant rather than the symptom: after normalization the
arguments that get announced, persisted and executed are one value.
"""

from __future__ import annotations

import json

import pytest

from nova.agent.core import Agent
from nova.llm.provider import ToolCall
from nova.tools.ask_user import AskUserToolBehavior, normalize_questions
from nova.tools.behavior import DefaultToolBehavior

RAW = [
    {"id": "platform", "question": "where?", "input_type": "select", "options": []},
    {"question": "how long?", "input_type": "select", "options": []},
    {"question": "which voice?", "input_type": "select", "options": []},
]


def _ids(questions: list) -> list[str]:
    return [q["id"] for q in questions]


def test_missing_ids_are_numbered_by_position() -> None:
    assert _ids(normalize_questions(RAW)) == ["platform", "q1", "q2"]


def test_a_blank_id_is_treated_as_missing() -> None:
    assert _ids(normalize_questions([{"id": "  ", "question": "q?"}])) == ["q0"]


def test_normalization_is_idempotent() -> None:
    once = normalize_questions(RAW)

    assert normalize_questions(once) == once


def test_behavior_fills_the_announced_arguments() -> None:
    behavior = AskUserToolBehavior()

    normalized = behavior.normalize_input({"questions": RAW})

    assert _ids(normalized["questions"]) == ["platform", "q1", "q2"]


def test_behavior_leaves_other_arguments_alone() -> None:
    behavior = AskUserToolBehavior()

    assert behavior.normalize_input({"other": 1}) == {"other": 1}


def test_behavior_ignores_a_non_list_questions_field() -> None:
    behavior = AskUserToolBehavior()

    assert behavior.normalize_input({"questions": "nope"}) == {"questions": "nope"}


def test_default_behavior_is_a_no_op() -> None:
    args = {"questions": RAW}

    assert DefaultToolBehavior().normalize_input(args) is args


def test_agent_rewrites_the_call_before_it_is_announced() -> None:
    """The end-to-end invariant: what is announced is what is executed."""
    agent = Agent.__new__(Agent)
    agent.tool_registry = _registry_with(AskUserToolBehavior())

    call = ToolCall(
        id="call-1",
        name="ask_user",
        arguments=json.dumps({"questions": RAW}),
    )
    agent._normalize_tool_arguments([call])

    announced = json.loads(call.arguments)
    executed = normalize_questions(announced["questions"])

    assert _ids(announced["questions"]) == ["platform", "q1", "q2"]
    # The tool normalizes again on its own; both passes must agree.
    assert executed == normalize_questions(RAW)


def test_untouched_when_the_model_got_it_right() -> None:
    agent = Agent.__new__(Agent)
    agent.tool_registry = _registry_with(AskUserToolBehavior())

    original = json.dumps({"questions": normalize_questions(RAW)})
    call = ToolCall(id="call-1", name="ask_user", arguments=original)

    agent._normalize_tool_arguments([call])

    assert call.arguments == original


def test_unparsable_arguments_are_left_for_the_existing_drop() -> None:
    agent = Agent.__new__(Agent)
    agent.tool_registry = _registry_with(AskUserToolBehavior())

    call = ToolCall(id="call-1", name="ask_user", arguments="{not json")

    agent._normalize_tool_arguments([call])

    assert call.arguments == "{not json"


def test_a_failing_normalizer_does_not_take_the_turn_down() -> None:
    class _Exploding:
        def normalize_input(self, args: dict) -> dict:
            raise RuntimeError("boom")

    agent = Agent.__new__(Agent)
    agent.tool_registry = _registry_with(_Exploding())

    original = json.dumps({"questions": RAW})
    call = ToolCall(id="call-1", name="ask_user", arguments=original)

    agent._normalize_tool_arguments([call])

    assert call.arguments == original


def test_a_tool_without_a_behavior_is_left_alone() -> None:
    agent = Agent.__new__(Agent)
    agent.tool_registry = _registry_with(DefaultToolBehavior())

    original = json.dumps({"questions": RAW})
    call = ToolCall(id="call-1", name="something_else", arguments=original)

    agent._normalize_tool_arguments([call])

    assert call.arguments == original


def _registry_with(behavior):
    from nova.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.set_behavior("ask_user", behavior)
    return registry


@pytest.mark.parametrize("bad", [None, 1, "text"])
def test_non_dict_arguments_pass_through(bad: object) -> None:
    agent = Agent.__new__(Agent)
    agent.tool_registry = _registry_with(AskUserToolBehavior())

    call = ToolCall(id="call-1", name="ask_user", arguments=json.dumps(bad))

    agent._normalize_tool_arguments([call])

    assert json.loads(call.arguments) == bad
