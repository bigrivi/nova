from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from nova.db.database import Message

if TYPE_CHECKING:
    from nova.session.manager import SessionContext


@runtime_checkable
class SessionProtocol(Protocol):
    def get_current_session(self) -> Optional[SessionContext]: ...

    async def create_session(
        self,
        *,
        persist: bool = True,
        first_message: str = None,
        agent_key: str = ...,
        metadata: Optional[dict] = None,
    ) -> SessionContext: ...

    async def load_session(self, session_id: str) -> Optional[SessionContext]: ...

    async def get_messages(
        self,
        session_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Message]: ...

    async def add_message(
        self,
        role: str,
        content: str,
        *,
        tool_calls: Optional[list] = None,
        tool_call_id: Optional[str] = None,
        images: Optional[list[str]] = None,
        reasoning_content: Optional[str] = None,
        group_id: Optional[str] = None,
        reasoning_elapsed_ms: Optional[int] = None,
    ) -> Message: ...
