"""Platform adapter contract.

Every messaging platform implements :class:`PlatformAdapter`. The gateway core
depends only on this interface, so platform-specific code stays behind it and
adding a platform is mechanical.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass
class InboundMessage:
    """One message received from a platform."""

    sender: str
    text: str
    attachments: list[dict] | None = None


MessageHandler = Callable[[InboundMessage], Awaitable[None]]


class PlatformAdapter(Protocol):
    """A messaging platform the gateway can drive Nova from."""

    name: str

    async def start(self) -> None:
        """Begin receiving messages. Return once the poll loop is running."""
        ...

    async def stop(self) -> None:
        """Stop receiving and release resources."""
        ...

    def on_message(self, handler: MessageHandler) -> None:
        """Register the inbound handler."""
        ...

    async def send_text(self, sender: str, text: str) -> None:
        """Send a text reply to *sender*."""
        ...

    async def send_file(self, sender: str, path: str) -> None:
        """Send a file to *sender*."""
        ...
