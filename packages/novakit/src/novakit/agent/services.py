"""Default in-memory services used by a standalone novakit agent."""

from __future__ import annotations

from novakit.agent.messages import convert_to_llm_messages
from novakit.agent.state import TurnState
from novakit.llm import Message
from novakit.llm.images import bound_images
from novakit.session.models import SessionContext
from novakit.session.protocol import SessionProtocol


class StaticPromptProvider:
    """Build provider messages from a fixed system prompt and session history."""

    def __init__(
        self,
        system_prompt: str,
        state: TurnState,
        session: SessionProtocol,
    ) -> None:
        self.system_prompt = system_prompt
        self.state = state
        self.session = session

    def apply_active_workspace(self, session: SessionContext | None) -> None:
        """Remember the session workspace without creating or changing directories.

        Args:
            session: Active session context, if one exists.
        """
        self.state.workspace = session.workspace_dir if session is not None else None

    async def build_messages(
        self, loaded_messages: list | None = None
    ) -> list[Message]:
        """Build a bounded provider request from the static prompt and history.

        Args:
            loaded_messages: Preloaded history, or None to read the active session.

        Returns:
            Provider-facing messages with the system prompt first.
        """
        if loaded_messages is None:
            loaded_messages = await self.session.get_messages()
        return bound_images(
            [
                Message(role="system", content=self.system_prompt),
                *convert_to_llm_messages(loaded_messages),
            ]
        )


class NoopBackground:
    """Default host hooks that intentionally schedule no application work."""

    def maybe_schedule_title_generation(
        self, session: SessionContext, first_message: str
    ) -> None:
        """Do nothing when a session is created.

        Args:
            session: Newly created session.
            first_message: First user text.
        """

    def maybe_schedule_memory_review(self, turn_count: int) -> None:
        """Do nothing when a request completes.

        Args:
            turn_count: Number of user turns in the conversation.
        """

    async def schedule_request_learning(
        self, tool_call_count: int, messages_before: int
    ) -> None:
        """Do nothing after a completed request.

        Args:
            tool_call_count: Tool calls made during the request.
            messages_before: Message count before the request started.
        """


__all__ = ["NoopBackground", "StaticPromptProvider"]
