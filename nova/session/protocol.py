from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from nova.session.models import Message

if TYPE_CHECKING:
    from nova.session.manager import SessionContext


@runtime_checkable
class SessionProtocol(Protocol):
    def get_current_session(self) -> SessionContext | None: ...

    async def create_session(
        self,
        *,
        persist: bool = True,
        first_message: str | None = None,
        agent_key: str = ...,
        metadata: dict | None = None,
    ) -> SessionContext: ...

    async def load_session(self, session_id: str) -> SessionContext | None: ...

    async def apply_generated_title(
        self, session_id: str, title: str, expected_title: str
    ) -> bool: ...

    async def get_messages(
        self,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[Message]: ...

    async def add_message(
        self,
        role: str,
        content: str,
        *,
        tool_calls: list | None = None,
        tool_call_id: str | None = None,
        images: list[str] | None = None,
        reasoning_content: str | None = None,
        group_id: str | None = None,
        reasoning_elapsed_ms: int | None = None,
        error: str | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
    ) -> Message: ...
