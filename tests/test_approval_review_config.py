"""The permission reviewer is reachable, and can run on a cheaper model.

It was not reachable. ``AgentConfig.shell_review`` was defined and read, and
``runtime.build_agent`` constructed ``AgentConfig`` without it, so nothing in the
product could ever set it True -- a whole feature behind a flag with no wiring,
documented as if it worked.

These pin the wiring end to end at the level it can be observed: the config
parses, the flag reaches the agent, and a configured provider overrides the
agent's own without changing any other behaviour.
"""

from __future__ import annotations

import pytest

from nova.settings import ApprovalReviewSettings, _parse_approval_review_config

# ── parsing ──────────────────────────────────────────────────────────


def test_absent_means_off() -> None:
    assert _parse_approval_review_config(None) == ApprovalReviewSettings()
    assert _parse_approval_review_config(None).enabled is False


def test_enabling_alone_keeps_the_agents_own_model() -> None:
    """The obvious first setting: on, with nothing else specified."""
    parsed = _parse_approval_review_config({"enabled": True})

    assert parsed.enabled is True
    assert parsed.provider == ""
    assert parsed.model == ""


def test_a_smaller_model_can_be_named() -> None:
    parsed = _parse_approval_review_config(
        {"enabled": True, "provider": "opencode_zen_free", "model": "space-bunny-free"}
    )

    assert parsed.provider == "opencode_zen_free"
    assert parsed.model == "space-bunny-free"


def test_a_model_without_a_provider_is_allowed() -> None:
    """Same provider as the agent, different model -- the common case."""
    parsed = _parse_approval_review_config({"enabled": True, "model": "small-model"})

    assert parsed.provider == ""
    assert parsed.model == "small-model"


def test_whitespace_is_trimmed() -> None:
    parsed = _parse_approval_review_config({"provider": "  p  ", "model": "  m  "})

    assert parsed.provider == "p"
    assert parsed.model == "m"


@pytest.mark.parametrize(
    "payload",
    [5, "yes", [], {"enabled": "true"}, {"enabled": 1}],
)
def test_a_malformed_block_is_rejected_loudly(payload: object) -> None:
    """Unlike permissions.json, a bad value here is not silently defaulted.

    ``approval_review`` decides whether a model gets to pre-approve actions. A
    typo that quietly read as "off" would look like the feature not working; one
    that quietly read as "on" would put a model in front of the approval path
    unasked. Both are worth a startup error.
    """
    with pytest.raises(ValueError):
        _parse_approval_review_config(payload)


# ── wiring ───────────────────────────────────────────────────────────


def _agent(**kwargs):
    from unittest.mock import MagicMock

    from nova.agent.core import Agent, AgentConfig

    return Agent(
        config=AgentConfig(model="big-model", provider="big", **kwargs),
        llm_provider=MagicMock(name="agent_llm"),
    )


@pytest.mark.asyncio
async def test_the_flag_reaches_the_tools() -> None:
    """The bug: nothing ever set this, so the reviewer never existed in production."""
    from nova.tools.behavior import PolicyToolBehavior, ShellToolBehavior

    off = _agent(shell_review=False)
    await off.register_all_tools()
    assert not isinstance(off.tool_registry.behavior_for("shell"), type(None))

    on = _agent(shell_review=True)
    await on.register_all_tools()
    behavior = on.tool_registry.behavior_for("shell")

    assert isinstance(behavior, ShellToolBehavior)
    assert behavior._reviewer is not None, "enabling it must actually build a reviewer"

    # And the reviewer reaches the tool axis too, not just the shell.
    assert isinstance(on.tool_registry.behavior_for("read"), PolicyToolBehavior)
    assert on.tool_registry.behavior_for("read")._reviewer is not None


def test_a_configured_provider_overrides_the_agents_own() -> None:
    """The point of the setting: do not spend the agent's budget on one word."""
    agent = _agent(shell_review=True)
    agent._review_llm = "cheap-provider-instance"
    agent._review_model = "cheap-model"

    from nova.tools.approval_review import build_reviewer

    reviewer = build_reviewer(
        agent._review_llm or agent.llm, agent._review_model or agent.config.model
    )

    assert callable(reviewer)
    assert agent._review_model == "cheap-model"


def test_no_configured_provider_falls_back_to_the_agent() -> None:
    agent = _agent(shell_review=True)

    assert agent._review_llm is None
    assert agent._review_model == ""
    assert (agent._review_llm or agent.llm) is agent.llm
    assert (agent._review_model or agent.config.model) == "big-model"
