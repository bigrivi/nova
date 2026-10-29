"""Console commands that run without a server: run, list, delete.

They drive :class:`ChatService` in-process instead of over HTTP, so ``nova run``
works in CI or a cron job with no backend listening, and ``nova sessions`` /
``nova delete`` work while the TUI is closed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import TextIO

from nova.constants import DEFAULT_AGENT_KEY
from nova.server.chat_service import ChatService
from nova.server.schemas import ChatRequest, stream_event_data_to_dict
from nova.settings import Settings

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_INPUT = 2
EXIT_INTERRUPTED = 130

#: Event type -> (exit code, field carrying the message, status name).
#: ``approval.required`` is in the table because a turn that stops to ask cannot
#: be answered from a console: leaving it out would park the process forever.
_TERMINAL: dict[str, tuple[int, str, str]] = {
    "response.completed": (EXIT_OK, "content", "completed"),
    "response.cancelled": (EXIT_ERROR, "message", "cancelled"),
    "response.error": (EXIT_ERROR, "message", "error"),
    "input.required": (EXIT_NEEDS_INPUT, "message", "input_required"),
    "approval.required": (EXIT_NEEDS_INPUT, "description", "approval_required"),
}

_TITLE_WIDTH = 60


async def run_prompt(
    prompt: str,
    *,
    settings: Settings,
    session_id: str | None = None,
    workspace_dir: str | None = None,
    agent_key: str = DEFAULT_AGENT_KEY,
    provider: str | None = None,
    model: str | None = None,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run one turn and return the process exit code.

    Args:
        prompt: The user message.
        settings: Runtime settings, normally from ``get_settings()``.
        session_id: Continue this session; a new one is created when omitted.
        workspace_dir: Workspace the tools are judged against; defaults to cwd.
        agent_key: Which agent answers.
        provider: Provider override for this turn.
        model: Model override for this turn.
        as_json: Emit one JSON object instead of streaming text to *out*.
        out: Stream for the answer, defaults to stdout.
        err: Stream for diagnostics, defaults to stderr.

    Returns:
        ``0`` completed, ``1`` error or cancellation, ``2`` the turn needs a
        human (input or approval), ``130`` interrupted.
    """
    out = out or sys.stdout
    err = err or sys.stderr
    service = ChatService(settings=settings)
    request = ChatRequest(
        session_id=session_id,
        message=prompt,
        provider=provider,
        model=model,
        agent_key=agent_key,
        workspace_dir=workspace_dir or str(Path.cwd()),
        # Nobody is at the keyboard, so a rule that would ask is refused instead
        # of waiting for an approval that can never arrive.
        permission_mode="dontAsk",
    )

    stream = service.chat_stream(request)
    resolved_session = session_id
    exit_code = EXIT_ERROR
    status = "error"
    final = ""
    streamed: list[str] = []
    try:
        async for event in stream:
            payload = stream_event_data_to_dict(event.data)
            resolved_session = payload.get("session_id") or resolved_session
            if event.type == "message.delta":
                delta = str(payload.get("delta") or "")
                streamed.append(delta)
                if not as_json:
                    out.write(delta)
                    out.flush()
                continue
            terminal = _TERMINAL.get(event.type)
            if terminal is None:
                continue
            exit_code, field, status = terminal
            final = str(payload.get(field) or "")
            break
    finally:
        # A turn parked on a human is abandoned here; closing the generator is
        # what stops the agent from waiting on an answer no one will send.
        await stream.aclose()

    if as_json:
        out.write(
            json.dumps(
                {
                    "session_id": resolved_session,
                    "status": status,
                    "message": final or "".join(streamed),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    elif not streamed:
        out.write(final + "\n")
    elif not "".join(streamed).endswith("\n"):
        out.write("\n")

    if exit_code != EXIT_OK:
        detail = final or status
        err.write(f"nova run: {status}: {detail}\n")
    return exit_code


async def list_sessions(
    *,
    settings: Settings,
    workspace_dir: str | None = None,
    all_workspaces: bool = False,
    as_json: bool = False,
    out: TextIO | None = None,
) -> int:
    """Print the user-visible sessions of one workspace, newest first.

    The default is the current directory, the same rule the TUI uses: a list that
    mixes every project on the machine is not a picker, it is a log.

    Args:
        settings: Runtime settings.
        workspace_dir: Workspace to list; defaults to the current directory.
        all_workspaces: Ignore the workspace filter (sessions from every project).
        as_json: Emit a JSON array instead of a table.
        out: Stream to write to, defaults to stdout.

    Returns:
        ``0`` on success.
    """
    out = out or sys.stdout
    workspace = None if all_workspaces else (workspace_dir or str(Path.cwd()))
    response = await ChatService(settings=settings).list_sessions(
        workspace_dir=workspace
    )
    items = response.items

    if as_json:
        out.write(
            json.dumps([item.model_dump() for item in items], ensure_ascii=False) + "\n"
        )
        return EXIT_OK

    if not items:
        if all_workspaces:
            out.write("No sessions\n")
        else:
            # Silence would read as "no sessions anywhere"; name the folder that
            # was searched and how to widen the search.
            out.write(f"No sessions in {workspace}\n")
            out.write("Use --all to list every workspace\n")
        return EXIT_OK

    rows = [
        (item.id, _format_time(item.updated_at), _one_line(item.title))
        for item in items
    ]
    id_width = max(len(row[0]) for row in rows)
    out.write(f"{'ID':<{id_width}}  {'UPDATED':<16}  TITLE\n")
    for session_id, updated, title in rows:
        out.write(f"{session_id:<{id_width}}  {updated:<16}  {title[:_TITLE_WIDTH]}\n")
    return EXIT_OK


async def delete_session(
    session_id: str,
    *,
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Delete one session and everything stored under it.

    Args:
        session_id: Id from ``nova sessions``.
        settings: Runtime settings.
        out: Stream for the confirmation, defaults to stdout.
        err: Stream for the failure, defaults to stderr.

    Returns:
        ``0`` when deleted, ``1`` when no such session exists.
    """
    out = out or sys.stdout
    err = err or sys.stderr
    if await ChatService(settings=settings).delete_session(session_id):
        out.write(f"Deleted session {session_id}\n")
        return EXIT_OK
    err.write(f"No session {session_id}\n")
    return EXIT_ERROR


async def rewind(
    session_id: str,
    checkpoint_id: str | None,
    *,
    settings: Settings,
    files_only: bool = False,
    force: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """List a session's rewind points, or roll back to one of them.

    Args:
        session_id: Session to rewind.
        checkpoint_id: A rewind point from the listing; None lists them instead.
        settings: Runtime settings.
        files_only: Restore files without dropping the conversation after them.
        force: Overwrite files that changed after the agent wrote them.
        out: Stream for results, defaults to stdout.
        err: Stream for failures, defaults to stderr.

    Returns:
        ``0`` on success, ``1`` when the session or checkpoint is unknown, or the
        session is mid-turn.
    """
    from nova import checkpoints as checkpoint_store
    from nova.session.errors import SessionBusy

    out = out or sys.stdout
    err = err or sys.stderr

    if checkpoint_id is None:
        items = checkpoint_store.list_checkpoints(session_id)
        if not items:
            out.write("No rewind points: no turn in this session changed a file\n")
            return EXIT_OK
        id_width = max(len(item.checkpoint_id) for item in items)
        out.write(f"{'CHECKPOINT':<{id_width}}  {'WHEN':<16}  FILES  LABEL\n")
        for item in items:
            label = _one_line(item.label)[:50]
            out.write(
                f"{item.checkpoint_id:<{id_width}}  "
                f"{_format_time(item.created_at):<16}  "
                f"{item.files:>5}  {label}\n"
            )
        return EXIT_OK

    try:
        result = await ChatService(settings=settings).rewind(
            session_id,
            checkpoint_id,
            force=force,
            keep_chat=files_only,
        )
    except SessionBusy as error:
        err.write(f"{error}\n")
        return EXIT_ERROR
    except FileNotFoundError as error:
        err.write(f"{error}\n")
        return EXIT_ERROR

    out.write(
        f"Restored {len(result['restored'])} file(s), "
        f"deleted {len(result['deleted'])}, "
        f"dropped {result['dropped_messages']} message(s)\n"
    )
    for item in result["skipped"]:
        out.write(f"  skipped {item['path']}: {item['reason']}\n")
    if not result["chat_truncated"]:
        out.write("  conversation kept (checkpoint message no longer in history)\n")
    return EXIT_OK


async def fork(
    session_id: str,
    *,
    settings: Settings,
    message_id: str | None = None,
    title: str | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Copy a session's conversation into a new one.

    Args:
        session_id: Session to copy.
        settings: Runtime settings.
        message_id: Last message to include; omitted copies the whole history.
        title: Title for the copy.
        out: Stream for the new session id, defaults to stdout.
        err: Stream for failures, defaults to stderr.

    Returns:
        ``0`` when forked, ``1`` when the session, the cut point, or the idle
        state is missing.
    """
    from nova.session.errors import SessionBusy
    from nova.session.fork import ForkPointNotFound

    out = out or sys.stdout
    err = err or sys.stderr

    try:
        result = await ChatService(settings=settings).fork_session(
            session_id, message_id=message_id, title=title
        )
    except SessionBusy as error:
        err.write(f"{error}\n")
        return EXIT_ERROR
    except FileNotFoundError as error:
        err.write(f"{error}\n")
        return EXIT_ERROR
    except ForkPointNotFound as error:
        err.write(f"{error}\n")
        return EXIT_ERROR

    out.write(
        f"Forked into {result['session_id']} "
        f"({result['messages']} message(s), {result['title']})\n"
    )
    return EXIT_OK


def _format_time(updated_at: int) -> str:
    """Render a session timestamp as local ``YYYY-MM-DD HH:MM``.

    Stored timestamps are milliseconds; anything that looks like seconds is
    accepted too so a row written by an older build still prints.
    """
    if not updated_at:
        return "-"
    seconds = updated_at / 1000 if updated_at > 10_000_000_000 else updated_at
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(seconds))


def _one_line(title: str | None) -> str:
    """Collapse a title to one line so it cannot break the table layout."""
    collapsed = " ".join((title or "").split())
    return collapsed or "(untitled)"
