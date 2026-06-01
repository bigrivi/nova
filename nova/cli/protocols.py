from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncGenerator, Protocol, runtime_checkable

from nova.agent.core import AgentEvent
from nova.cli.commands import CommandDispatcher, CommandRegistry
from nova.cli.screens import AgentCreateResult
from nova.cli.ui import ModelGroup, ModelSelection, SessionSelection


@dataclass(frozen=True)
class ChatStatus:
    model_label: str
    provider_label: str


class AgentStreamProtocol(Protocol):
    async def chat_stream(
        self,
        user_input: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        ...

    def interrupt(self) -> None:
        ...


@runtime_checkable
class ChatControllerProtocol(Protocol):
    @property
    def agent(self) -> AgentStreamProtocol:
        ...

    @property
    def command_registry(self) -> CommandRegistry:
        ...

    @property
    def command_dispatcher(self) -> CommandDispatcher:
        ...

    @property
    def pending_input(self) -> dict[str, Any] | None:
        ...

    async def stream_chat_events(
        self,
        user_input: str,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        ...

    def get_status(self) -> ChatStatus:
        ...

    def get_session_id(self) -> str | None:
        ...

    def set_session_id(self, session_id: str | None) -> None:
        ...

    def set_pending_input(self, payload: dict[str, Any]) -> None:
        ...

    def reset_pending_input(self) -> None:
        ...

    def reset_stop_requested(self) -> None:
        ...

    def request_stop(self) -> None:
        ...


class StreamControllerProtocol(Protocol):
    async def stream_chat_events(
        self,
        user_input: str,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        ...

    def set_pending_input(self, payload: dict[str, Any]) -> None:
        ...


class UIAdapterProtocol(Protocol):
    def shutdown(self) -> None:
        ...

    def clear_screen(self) -> None:
        ...

    def show_info(self, text: str) -> None:
        ...

    def show_error(self, text: str) -> None:
        ...

    def info(self, text: str) -> None:
        ...

    def error(self, text: str) -> None:
        ...

    def update_status_bar(self) -> None:
        ...

    def print_history_transcript(self, history: list[object]) -> None:
        ...

    async def prompt_model_selection(
        self,
        groups: list[ModelGroup],
        *,
        current_provider: str,
        current_model: str,
    ) -> ModelSelection | None:
        ...

    async def prompt_session_selection(
        self,
        sessions: list[dict],
        *,
        current_session_id: str | None,
    ) -> SessionSelection | None:
        ...

    async def prompt_agent_list(self, agents: list[dict]) -> None:
        ...

    async def prompt_create_agent(self) -> AgentCreateResult | None:
        ...

    async def prompt_delete_agent(self, agents: list[dict]) -> str | None:
        ...

    async def prompt_delete_confirm(self, agent_key: str, session_count: int) -> bool:
        ...
