"""DataSource-backed persistence for context compaction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from novakit.session.models import Message, NewMessage

if TYPE_CHECKING:
    from nova.db.data_source import DataSourceProtocol


class DataSourceCompactionStore:
    """A novakit ``CompactionStore`` over Nova's database.

    Stateless: every call delegates to the wrapped data source, which owns
    sessions, messages and compaction bookkeeping.
    """

    def __init__(self, db: DataSourceProtocol) -> None:
        """Wrap *db*; no state is kept on the store itself.

        Args:
            db: Nova data source owning the session's messages.
        """
        self._db = db

    async def update_message_content(self, message_id: str, content: str) -> None:
        """Replace a snipped tool result's stored content.

        Args:
            message_id: Message to update.
            content: Trimmed content to persist.
        """
        await self._db.update_message_content(message_id, content)

    async def add_summary(
        self, session_id: str, content: str, time_created: int
    ) -> Message:
        """Persist the summary message replacing compacted history.

        Args:
            session_id: Session the summary belongs to.
            content: Summary text to store.
            time_created: Backdated stamp placing it at the fold boundary.

        Returns:
            The persisted summary message.
        """
        return await self._db.add_message(
            NewMessage(
                session_id=session_id,
                role="assistant",
                content=content,
                summary=True,
                time_created=time_created,
            )
        )

    async def mark_messages_compacted_by_ids(
        self, session_id: str, message_ids: list[str]
    ) -> None:
        """Hide compacted messages from later history reads.

        Args:
            session_id: Session owning the messages.
            message_ids: Messages to hide.
        """
        await self._db.mark_messages_compacted_by_ids(session_id, message_ids)

    async def update_session_compacted_at(
        self, session_id: str, timestamp: int
    ) -> None:
        """Record when the last successful compaction ran.

        Args:
            session_id: Session to stamp.
            timestamp: Successful-compaction time in milliseconds.
        """
        await self._db.update_session_compacted_at(session_id, timestamp)

    async def get_messages(self, session_id: str) -> list:
        """Return the session's visible messages oldest-first.

        Args:
            session_id: Session to read.

        Returns:
            Visible messages in chronological order.
        """
        return await self._db.get_messages(session_id)


__all__ = ["DataSourceCompactionStore"]
