"""Old Nova import paths remain aliases of the extracted novakit objects."""

from novakit import agent as novakit_agent
from novakit import events as novakit_events
from novakit import llm as novakit_llm
from novakit import session as novakit_session
from novakit import tools as novakit_tools

from nova import agent as nova_agent
from nova import llm as nova_llm
from nova import tools as nova_tools
from nova.agent import llm_stream as nova_llm_stream
from nova.agent import state as nova_agent_state
from nova.agent import tool_guardrails as nova_tool_guardrails
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


def test_agent_primitives_have_one_identity() -> None:
    assert nova_llm_stream.TurnStreamReader is novakit_agent.TurnStreamReader
    assert nova_llm_stream.TurnOutcome is novakit_agent.TurnOutcome
    assert nova_agent_state.TurnState is novakit_agent.TurnState
    assert nova_tool_guardrails.ToolGuardrails is novakit_agent.ToolGuardrails
    assert nova_tool_guardrails.GuardrailAction is novakit_agent.GuardrailAction
    assert (
        nova_tool_guardrails.GuardrailObservation is novakit_agent.GuardrailObservation
    )


def test_nova_agent_extends_novakit_runtime() -> None:
    from nova.agent.core import Agent as NovaAgent

    assert issubclass(NovaAgent, novakit_agent.Agent)


def test_tool_registry_has_one_identity() -> None:
    from nova.tools import context as nova_tool_context

    assert nova_tools.ToolRegistry is novakit_tools.ToolRegistry
    assert nova_tools.tool is novakit_tools.tool
    assert nova_tool_context.ToolContext is novakit_tools.ToolContext


def test_agent_leaf_modules_have_one_identity() -> None:
    import novakit

    from nova import agent as nova_agent_pkg
    from nova.agent import compaction as nova_compaction
    from nova.agent import core as nova_core
    from nova.agent import messaging as nova_messaging
    from nova.agent import overflow as nova_overflow
    from nova.agent import protocol as nova_protocol
    from nova.agent import session as nova_agent_session
    from nova.agent import tool_invoker as nova_tool_invoker
    from nova.agent.compaction import orchestrator as nova_orchestrator

    assert nova_core.AgentConfig is novakit.AgentConfig
    assert nova_core.AgentConfig is novakit_agent.AgentConfig
    assert nova_agent_pkg.AgentConfig is novakit.AgentConfig
    assert nova_core.build_user_message is novakit_agent.build_user_message
    assert nova_messaging.count_user_turns is novakit_agent.count_user_turns
    assert (
        nova_messaging.convert_to_llm_messages is novakit_agent.convert_to_llm_messages
    )
    assert nova_overflow.is_context_overflow is novakit_agent.is_context_overflow
    assert nova_overflow.OVERFLOW_PATTERNS is novakit_agent.OVERFLOW_PATTERNS
    assert nova_overflow.NON_OVERFLOW_PATTERNS is novakit_agent.NON_OVERFLOW_PATTERNS
    assert nova_protocol.ChatAgent is novakit_agent.ChatAgent
    assert nova_protocol.InterruptibleAgent is novakit_agent.InterruptibleAgent
    assert nova_agent_session.AgentSessionContext is novakit_agent.AgentSessionContext
    assert nova_tool_invoker.ToolInvoker is novakit_agent.ToolInvoker
    assert nova_tool_invoker.ToolOutcome is novakit_agent.ToolOutcome
    assert nova_tool_invoker.parse_tool_arguments is novakit_agent.parse_tool_arguments
    assert (
        nova_tool_invoker.has_parsable_arguments is novakit_agent.has_parsable_arguments
    )
    assert nova_compaction.CompactionError is novakit_agent.CompactionError
    assert nova_orchestrator.CompactionError is novakit_agent.CompactionError
