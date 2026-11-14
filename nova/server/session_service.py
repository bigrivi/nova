"""Session and project operations, split out of ChatService."""

from __future__ import annotations

import inspect
import logging
import time

from nova.app import build_agent
from nova.constants import DEFAULT_AGENT_KEY
from nova.db import DataSourceProtocol, get_default_data_source
from nova.project.service import ProjectService
from nova.server.request_registry import _RESERVED, ACTIVE, DETACHED, RequestRegistry
from nova.server.schemas import (
    MessageListResponse,
    MessageRecord,
    SessionListResponse,
    SessionSummary,
)
from nova.server.stream_buffer import StreamBuffer
from nova.session.history_projection import get_user_visible_history
from nova.session.models import decode_display_text
from nova.settings import Settings

log = logging.getLogger(__name__)


async def _turn_is_running(registry: RequestRegistry, session_id: str) -> bool:
    """True only while a stream holds the session.

    A finished turn keeps its slot for resume/status until the reaper evicts it
    (``TERMINAL_TTL``), so asking whether a slot *exists* reports a session as
    busy for ten minutes after every reply. Fork, rewind and compact care about
    a live writer, which is what ``active``/``detached`` mean.
    """
    return await registry.slot_state(session_id) in (ACTIVE, DETACHED)


def normalize_workspace_dir(workspace_dir: str | None) -> str | None:
    """Trim, expand ~, and resolve a workspace path; blank/None clears it."""
    if not workspace_dir or not workspace_dir.strip():
        return None
    from pathlib import Path

    try:
        return str(Path(workspace_dir.strip()).expanduser().resolve())
    except OSError:
        return workspace_dir.strip()


def _content_with_attachments(original: str, text: str) -> str:
    """The new question, keeping the attachment references the client appended.

    A message can carry ``Attached file: `path` `` lines: they are how the model
    learns that a file exists. Replacing the question must not silently drop
    them -- the files are still attached, and the model still has to be told.
    """
    references = [
        line for line in original.splitlines() if line.startswith("Attached ")
    ]
    return "\n".join([text, *references]) if references else text


class SessionService:
    """Sessions, projects and workspace lookups behind the HTTP routes."""

    def __init__(
        self,
        settings: Settings,
        data_source: DataSourceProtocol | None = None,
        request_registry: RequestRegistry | None = None,
        stream_buffer: StreamBuffer | None = None,
    ) -> None:
        self._settings = settings
        self._data_source = data_source
        self._request_registry = request_registry or RequestRegistry()
        self._stream_buffer = stream_buffer or StreamBuffer()
        self._request_registry.attach_buffer(self._stream_buffer)

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings

    async def _get_data_source(self) -> DataSourceProtocol:
        if self._data_source is None:
            self._data_source = await get_default_data_source()
        return self._data_source

    async def list_sessions(
        self,
        agent_key: str | None = None,
        workspace_dir: str | None = None,
    ) -> SessionListResponse:
        data_source = await self._get_data_source()
        sessions = await data_source.get_all_sessions(agent_key=agent_key)
        # Sub-agents run internal child sessions; those are not user-facing
        # conversations, so only primary-agent sessions belong in the list.
        subagent_keys = await self._subagent_agent_keys(data_source)
        if subagent_keys:
            sessions = [
                session
                for session in sessions
                if session.get("agent_key", DEFAULT_AGENT_KEY) not in subagent_keys
            ]
        normalized_workspace = normalize_workspace_dir(workspace_dir)
        if normalized_workspace is not None:
            # Normalize rows too: /tmp vs /private/tmp and trailing separators
            # would otherwise silently drop sessions of the same directory.
            sessions = [
                session
                for session in sessions
                if normalize_workspace_dir(session.get("workspace_dir"))
                == normalized_workspace
            ]
        items = [
            SessionSummary(
                id=session["id"],
                title=session.get("title"),
                updated_at=session.get("updated_at", 0),
                agent_key=session.get("agent_key", DEFAULT_AGENT_KEY),
                workspace_dir=session.get("workspace_dir"),
                pinned=bool(session.get("pinned", 0)),
                project_id=session.get("project_id"),
                forked_from=session.get("forked_from"),
                fork_point_message_id=session.get("fork_point_message_id"),
            )
            for session in sessions
        ]
        return SessionListResponse(items=items)

    async def _subagent_agent_keys(self, data_source: DataSourceProtocol) -> set[str]:
        """Keys of agents whose mode is ``subagent``.

        Sub-agent sessions are internal delegation children, not user-facing
        conversations, so they are excluded from the session list. Returns an
        empty set when the catalog cannot be loaded, so a transient failure
        never hides legitimate sessions.
        """
        try:
            agents = await data_source.list_agents()
        except Exception:
            log.exception("Failed to load agents while filtering sessions")
            return set()
        return {
            agent["key"]
            for agent in agents
            if (agent.get("mode") or "primary") == "subagent"
        }

    async def rename_session(self, session_id: str, title: str) -> bool:
        data_source = await self._get_data_source()
        return await data_source.update_session_title(session_id, title)

    async def set_session_workspace(
        self, session_id: str, workspace_dir: str | None
    ) -> bool:
        data_source = await self._get_data_source()
        normalized = normalize_workspace_dir(workspace_dir)
        return await data_source.set_session_workspace(session_id, normalized)

    async def set_session_pinned(self, session_id: str, pinned: bool) -> bool:
        data_source = await self._get_data_source()
        return await data_source.set_session_pinned(session_id, pinned)

    async def set_session_project(
        self, session_id: str, project_id: str | None
    ) -> bool:
        return await ProjectService(self._data_source).set_session_project(
            session_id, project_id
        )

    async def list_projects(self) -> list[dict]:
        return await ProjectService(self._data_source).list_projects()

    async def create_project(self, name: str | None, path: str | None) -> dict:
        return await ProjectService(self._data_source).create_project(name, path)

    async def update_project(self, project_id: str, **fields: object) -> dict | None:
        return await ProjectService(self._data_source).update_project(
            project_id, **fields
        )

    async def delete_project(self, project_id: str) -> bool:
        return await ProjectService(self._data_source).delete_project(project_id)

    async def resolve_project_for_path(
        self, path: str, name: str | None = None
    ) -> dict:
        return await ProjectService(self._data_source).resolve_for_path(path, name)

    async def delete_session(
        self, session_id: str, delete_memories: bool = False
    ) -> bool:
        data_source = await self._get_data_source()
        owner = await self._request_registry.get(session_id)
        if owner is not None:
            if owner is not _RESERVED:
                terminate_fn = getattr(owner, "terminate", None)
                if callable(terminate_fn):
                    try:
                        result = terminate_fn()
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        log.exception(
                            "delete_session terminate failed for %s", session_id
                        )
                await self._request_registry.unregister(session_id)
            else:
                await self._request_registry.unregister(session_id)
        try:
            self._stream_buffer.discard(session_id)
        except Exception:
            log.exception("delete_session buffer discard failed for %s", session_id)
        from nova.prompt.session_cache import forget_session

        forget_session(session_id)
        deleted = await data_source.delete_session(session_id)
        if deleted:
            from nova.tools.checkpoints import remove_session

            remove_session(session_id)
            from nova.tasks.manager import get_background_task_manager

            await get_background_task_manager().cancel_for_session(session_id)
        if deleted and delete_memories:
            from nova.memory.service import MemoryService

            await MemoryService().delete_by_session(session_id)
        return deleted

    async def rewind(
        self,
        session_id: str,
        checkpoint_id: str,
        *,
        force: bool = False,
        keep_chat: bool = False,
    ) -> dict[str, object]:
        """Undo the files a turn changed and drop the turns after it.

        The chat is only truncated when the checkpoint's user message is still in
        the visible history; a compaction that rewrote it away would otherwise
        make "delete everything after index -1" delete the whole session.

        Args:
            session_id: Session the checkpoint belongs to.
            checkpoint_id: The turn's user message id.
            force: Restore files that changed after the agent wrote them.
            keep_chat: Restore files only, leaving the conversation intact.

        Returns:
            The restore report plus how many messages were dropped.

        Raises:
            SessionBusy: when a turn is still streaming in this session.
            FileNotFoundError: when the checkpoint does not exist.
        """
        from nova import checkpoints as checkpoint_store
        from nova.session.errors import SessionBusy

        if await _turn_is_running(self._request_registry, session_id):
            raise SessionBusy(session_id, "rewind")

        report = checkpoint_store.restore_files(session_id, checkpoint_id, force=force)
        dropped = 0
        chat_truncated = False
        if not keep_chat:
            response = await self.list_messages(session_id)
            ids = [message.id for message in response.items]
            if checkpoint_id in ids:
                stale = ids[ids.index(checkpoint_id) :]
                data_source = await self._get_data_source()
                dropped = await data_source.delete_messages(session_id, stale)
                checkpoint_store.discard_checkpoints_from(session_id, checkpoint_id)
                chat_truncated = True

        return {
            "restored": report.restored,
            "deleted": report.deleted,
            "skipped": report.skipped,
            "dropped_messages": dropped,
            "chat_truncated": chat_truncated,
        }

    async def edit_message(
        self,
        session_id: str,
        message_id: str,
        text: str,
        *,
        force: bool = False,
    ) -> dict[str, object]:
        """Replace a question and answer it again.

        The message keeps its place and its id, so the checkpoint that belongs
        to it still names a real turn; everything after it is dropped -- the
        answers, the tool calls, and the files the agent changed in the turns
        that followed. The turn that follows runs on the new text.

        Args:
            session_id: Session the message belongs to.
            message_id: The user message to replace.
            text: The question as it should now read.
            force: Restore files that changed after the agent wrote them.

        Returns:
            The restore report, how many messages were dropped, and the id of
            the message that now carries the new text.

        Raises:
            SessionBusy: when a turn is still streaming in this session.
            FileNotFoundError: when the message does not exist.
            ValueError: when the message is not a question, or the text is empty.
        """
        from nova import checkpoints as checkpoint_store
        from nova.session.errors import SessionBusy

        if await _turn_is_running(self._request_registry, session_id):
            raise SessionBusy(session_id, "edit")

        new_text = text.strip()
        if not new_text:
            raise ValueError("The edited question is empty")

        response = await self.list_messages(session_id)
        ids = [message.id for message in response.items]
        if message_id not in ids:
            raise FileNotFoundError(f"Message {message_id} not found in {session_id}")
        target = response.items[ids.index(message_id)]
        if target.role != "user":
            raise ValueError("Only a question can be edited")

        # The files first: the restore reads the checkpoint the old turn wrote,
        # and the checkpoints are dropped below.
        try:
            report = checkpoint_store.restore_files(session_id, message_id, force=force)
        except FileNotFoundError:
            # A turn that changed no file has no checkpoint: there is nothing to
            # put back, which is not a failure.
            report = checkpoint_store.RestoreReport()

        stale = ids[ids.index(message_id) + 1 :]
        data_source = await self._get_data_source()
        dropped = await data_source.delete_messages(session_id, stale) if stale else 0

        content = _content_with_attachments(target.content or "", new_text)
        await data_source.update_message_content(message_id, content)
        # The old turn is gone, so its rewind point is too. The turn that
        # follows records a fresh one under the same message id.
        checkpoint_store.discard_checkpoints_from(session_id, message_id)

        return {
            "message_id": message_id,
            "restored": report.restored,
            "deleted": report.deleted,
            "skipped": report.skipped,
            "dropped_messages": dropped,
        }

    async def usage(
        self,
        session_id: str | None = None,
        days: int | None = None,
    ) -> dict[str, object]:
        """Token and cost totals, for one session or for every session.

        The cost is an estimate: prices come from the catalogue, and a model it
        does not price is reported as unknown rather than free. Tokens are what
        the provider reported, summed.

        Args:
            session_id: Restrict to this session; None counts every session.
            days: Only messages newer than this many days, when set.

        Returns:
            Totals, the per-model breakdown, and the session's own facts when
            one was named.

        Raises:
            FileNotFoundError: when *session_id* names a session that is gone.
        """
        from nova.registry import pricing

        since = None
        if days is not None and days > 0:
            since = int(time.time() * 1000) - days * 86_400_000

        data_source = await self._get_data_source()
        rows = await data_source.usage_by_model(session_id, since)
        cost = pricing.usage_cost(self._settings, rows)

        totals = {
            "input": sum(int(row.get("input") or 0) for row in rows),
            "output": sum(int(row.get("output") or 0) for row in rows),
            "cache_read": sum(int(row.get("cache_read") or 0) for row in rows),
        }
        totals["total"] = totals["input"] + totals["output"]

        session = None
        if session_id is not None:
            record = await data_source.get_session(session_id)
            if record is None:
                raise FileNotFoundError(f"Session {session_id} not found")
            session = {
                "turns": int(record.get("turn_count") or 0),
                "messages": int(record.get("message_count") or 0),
                "started_at": int(record.get("created_at") or 0),
                "updated_at": int(record.get("updated_at") or 0),
            }

        return {
            "scope": "session" if session_id is not None else "all",
            "days": days,
            "since": since,
            "tokens": totals,
            "cost": cost,
            "messages": sum(int(row.get("messages") or 0) for row in rows),
            "by_model": rows,
            "session": session,
        }

    async def compact(self, session_id: str) -> dict[str, object]:
        """Force one compaction pass so the user can free context on demand.

        Args:
            session_id: Session to compact.

        Returns:
            ``{"compacted": bool}``: False when the history is not splittable yet.

        Raises:
            SessionBusy: when a turn is streaming in this session.
            FileNotFoundError: when the session does not exist.
        """
        from nova.constants import DEFAULT_AGENT_KEY
        from nova.session.errors import SessionBusy

        if await _turn_is_running(self._request_registry, session_id):
            raise SessionBusy(session_id, "compact")

        data_source = await self._get_data_source()
        record = await data_source.get_session(session_id)
        if record is None:
            raise FileNotFoundError(f"Session {session_id} not found")

        agent = await build_agent(
            agent_key=record.get("agent_key") or DEFAULT_AGENT_KEY,
            session_id=session_id,
            data_source=data_source,
        )
        return await agent.compact_now(session_id)

    async def workspace_of(self, session_id: str) -> str | None:
        """The workspace directory a session runs in, or None.

        Routers that shell out (git) need the session's tree, not the server
        process's cwd: the two are different as soon as one client changes
        directory.

        Args:
            session_id: Session to look up.

        Returns:
            The stored absolute path, or None when the session has no workspace.

        Raises:
            FileNotFoundError: when the session does not exist, so a caller can
                answer 404 rather than blaming the workspace.
        """
        data_source = await self._get_data_source()
        record = await data_source.get_session(session_id)
        if record is None:
            raise FileNotFoundError(f"Session {session_id} not found")
        workspace = record.get("workspace_dir")
        return str(workspace) if workspace else None

    async def route_of(self, session_id: str) -> tuple[str | None, str | None]:
        """The provider and model a session was last run with.

        Args:
            session_id: Session to look up.

        Returns:
            ``(provider, model)``; either may be None for a session that never
            recorded a route.

        Raises:
            FileNotFoundError: when the session does not exist.
        """
        data_source = await self._get_data_source()
        record = await data_source.get_session(session_id)
        if record is None:
            raise FileNotFoundError(f"Session {session_id} not found")
        return record.get("provider"), record.get("model")

    async def fork_session(
        self,
        session_id: str,
        *,
        message_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, object]:
        """Copy a conversation into a new session, leaving the original alone.

        Args:
            session_id: Session to copy.
            message_id: Last message to include; omitted copies everything.
            title: Title for the copy.

        Returns:
            The new session's id, title and message count.

        Raises:
            SessionBusy: when a turn is streaming in the source session.
            FileNotFoundError: when the source session does not exist.
            ForkPointNotFound: when *message_id* is not in the source session.
        """
        from nova.session.errors import SessionBusy
        from nova.session.fork import fork_session

        if await _turn_is_running(self._request_registry, session_id):
            raise SessionBusy(session_id, "fork")

        data_source = await self._get_data_source()
        return await fork_session(
            data_source, session_id, message_id=message_id, title=title
        )

    async def list_messages(self, session_id: str) -> MessageListResponse:
        data_source = await self._get_data_source()
        messages = await get_user_visible_history(data_source, session_id)
        items = [
            MessageRecord(
                id=message.id,
                session_id=message.session_id,
                role=message.role,
                content=message.content,
                tool_call_id=message.tool_call_id,
                tool_calls=message.tool_calls or [],
                time_created=message.time_created,
                images=message.images,
                reasoning_content=message.reasoning_content,
                reasoning_elapsed_ms=message.reasoning_elapsed_ms,
                tokens_input=message.tokens_input,
                cache_read_tokens=message.cache_read_tokens,
                group_id=message.group_id,
                error=message.error,
                variant=message.variant,
                display_text=decode_display_text(message.data),
            )
            for message in messages
        ]
        return MessageListResponse(items=items)

    async def get_session_route(self, session_id: str) -> dict | None:
        """The route a session runs with, for restoring it when reopened.

        Separate from the message history on purpose: opening a conversation has
        to know the model and effort before any message is loaded, and a history
        scan would have to guess which of the last few turns still applies.
        """
        data_source = await self._get_data_source()
        session = await data_source.get_session(session_id)
        if session is None:
            return None
        return {
            "provider": session.get("provider"),
            "model": session.get("model"),
            "reasoning_effort": session.get("reasoning_effort"),
        }

    async def set_session_route(
        self,
        session_id: str,
        provider: str | None,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        """Record a session's route, dropping a level its model cannot take.

        Validated on the way in rather than only at agent build time, so what a
        later GET hands back is always a level the model actually accepts.
        """
        if provider and model and reasoning_effort:
            from nova.llm.reasoning import fit_effort, resolve_effort_levels

            provider_config = self._settings.providers.get(provider)
            if provider_config is not None:
                levels = resolve_effort_levels(
                    model,
                    provider_config.type,
                    provider_config.models.get(model)
                    if isinstance(provider_config.models, dict)
                    else None,
                )
                reasoning_effort = fit_effort(levels, reasoning_effort)
        data_source = await self._get_data_source()
        return await data_source.set_session_route(
            session_id, provider, model, reasoning_effort
        )

    async def get_context(
        self, session_id: str, provider: str | None = None, model: str | None = None
    ) -> dict:
        from nova.agent.compaction import (
            compaction_threshold,
            estimate_context_tokens,
            get_context_limit,
        )

        data_source = await self._get_data_source()
        # Use raw messages for accurate compaction-aligned estimation
        try:
            raw_messages = await data_source.get_messages(session_id)
        except Exception:
            raw_messages = []
        try:
            session = await data_source.get_session(session_id)
        except Exception:
            session = None
        # Resolve provider/model: explicit query wins, then the route the session
        # actually ran with, then its agent's default. The session comes before
        # the agent because the agent holds only the route a *new* conversation
        # starts from -- once a session switched model, reading the agent divided
        # its prompt by the window of a model it never ran on.
        if (not provider or not model) and session:
            provider = provider or session.get("provider")
            model = model or session.get("model")
        if not provider or not model:
            agent_key = session.get("agent_key") if session else None
            if agent_key:
                from nova.config.service import ConfigService

                try:
                    service = ConfigService(self._settings, data_source)
                    agent = await service.get_agent(agent_key)
                except Exception:
                    agent = None
                if agent:
                    provider = provider or agent.get("provider")
                    model = model or agent.get("model")
        if not provider or not model:
            # Fallback to first configured provider/model
            first_provider = next(iter(self._settings.providers.keys()), None)
            if first_provider:
                provider = provider or first_provider
                model = model or next(
                    iter(self._settings.providers[first_provider].models.keys()),
                    "gpt-4o",
                )
            else:
                provider = provider or "ollama"
                model = model or "gpt-4o"
        used = estimate_context_tokens(
            raw_messages,
            model or "unknown",
            session.get("compacted_at") if session else None,
        )
        # Against the compaction threshold, not the raw window: that is what the
        # streaming CONTEXT_UPDATE frame reports, and both feed the same pill.
        # Dividing one by the window and the other by the threshold made the
        # percentage jump the moment a turn started -- 62% on open, 76% in the
        # stream, for the same history -- and changed what `limit` meant too.
        limit = compaction_threshold(
            get_context_limit(model or "unknown", provider or "ollama")
        )
        percent = int(used / limit * 100) if limit else 0
        # Cache accounting comes from what the provider charged, never from
        # `used`: that one is anchored on a real prompt size but its tail is a
        # character estimate, and a ratio mixing the two is a ratio of nothing.
        # Both sides are summed over the turns that reported a cache figure, so a
        # turn whose provider stayed silent drops out entirely -- counting it as
        # a miss would invent a hit rate for a gateway that never mentioned
        # caching. A reported zero still counts, because it is a real miss.
        billed = [
            (message.tokens_input, message.cache_read_tokens)
            for message in raw_messages
            if message.tokens_input is not None
            and message.tokens_input != 0
            and message.cache_read_tokens is not None
        ]
        prompt_tokens = sum(tokens for tokens, _ in billed)
        cached_tokens = sum(cached for _, cached in billed)
        return {
            "used": used,
            "limit": limit,
            "percent": percent,
            "message_count": len(raw_messages),
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "hit_rate": (
                round(cached_tokens / prompt_tokens * 100, 1) if prompt_tokens else None
            ),
        }
