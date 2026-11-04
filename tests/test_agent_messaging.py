"""AgentMessaging works on a context and turn state, not on an Agent."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from nova.agent.messaging import AgentMessaging
from nova.agent.state import TurnState
from nova.prompt.builder import PromptBuilder, PromptConfig
from nova.tools.workspace_context import get_active_workspace, set_active_workspace


@pytest.fixture(autouse=True)
def _clear_workspace():
    set_active_workspace(None)
    yield
    set_active_workspace(None)


def _messaging(state: TurnState, agent_dir: Path = Path("/agent")) -> AgentMessaging:
    """The smallest context AgentMessaging actually reads -- no Agent anywhere."""
    ctx = SimpleNamespace(
        agent_dir=agent_dir,
        agent_key="main",
        is_sub_agent=False,
        skill_service=SimpleNamespace(list_skills=lambda: []),
        prompt_builder=PromptBuilder(PromptConfig(workspace_dir=str(agent_dir))),
        session=None,
        learning_loop=None,
    )
    return AgentMessaging(ctx, state)  # type: ignore[arg-type]


def test_applying_a_workspace_updates_state_and_drops_the_cached_prompt(tmp_path):
    state = TurnState(base_system_prompt="cached")
    messaging = _messaging(state)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    messaging.apply_active_workspace(SimpleNamespace(workspace_dir=str(workspace)))

    assert state.workspace == str(workspace.resolve())
    assert state.base_system_prompt is None, "a new workspace invalidates the prefix"
    assert get_active_workspace() == str(workspace.resolve())


def test_the_system_prompt_uses_the_turn_state_workspace(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    state = TurnState(workspace=str(workspace))
    messaging = _messaging(state)

    prompt = messaging.build_system_prompt()

    assert str(workspace) in prompt


def test_no_workspace_falls_back_to_the_agent_directory():
    messaging = _messaging(TurnState(), agent_dir=Path("/agent/dir"))

    prompt = messaging.build_system_prompt()

    assert "/agent/dir" in prompt
