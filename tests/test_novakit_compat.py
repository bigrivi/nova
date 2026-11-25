"""Old Nova import paths remain aliases of the extracted novakit objects."""

from novakit import events as novakit_events
from novakit import llm as novakit_llm
from novakit import session as novakit_session
from novakit import tools as novakit_tools

from nova import agent as nova_agent
from nova import llm as nova_llm
from nova import tools as nova_tools
from nova.session import models as nova_session_models
from nova.session import protocol as nova_session_protocol


def test_llm_types_have_one_identity() -> None:
    assert nova_llm.Message is novakit_llm.Message
    assert nova_llm.ToolCall is novakit_llm.ToolCall
    assert nova_llm.ToolResult is novakit_llm.ToolResult
    assert nova_llm.Done is novakit_llm.Done


def test_event_types_have_one_identity() -> None:
    assert nova_agent.AgentEvent is novakit_events.AgentEvent
    assert nova_agent.EventBus is novakit_events.EventBus


def test_session_models_have_one_identity() -> None:
    assert nova_session_protocol.SessionProtocol is novakit_session.SessionProtocol
    assert nova_session_models.Message is novakit_session.Message
    assert nova_session_models.SessionContext is novakit_session.SessionContext


def test_tool_registry_has_one_identity() -> None:
    assert nova_tools.ToolRegistry is novakit_tools.ToolRegistry
    assert nova_tools.tool is novakit_tools.tool
