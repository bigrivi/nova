"""Nova's public SDK exports share the standalone novakit implementations."""

from novakit import Agent as CoreAgent
from novakit import AgentConfig
from novakit import events as novakit_events
from novakit import llm as novakit_llm
from novakit import tools as novakit_tools

from nova import AgentEvent, Message, ToolRegistry, tool
from nova.agent.core import Agent as NovaAgent


def test_nova_public_sdk_exports_share_identity() -> None:
    assert AgentEvent is novakit_events.AgentEvent
    assert Message is novakit_llm.Message
    assert ToolRegistry is novakit_tools.ToolRegistry
    assert tool is novakit_tools.tool


def test_nova_agent_extends_novakit_runtime() -> None:
    assert issubclass(NovaAgent, CoreAgent)


def test_nova_agent_config_is_novakit_agent_config() -> None:
    from nova import AgentConfig as NovaAgentConfig

    assert NovaAgentConfig is AgentConfig
