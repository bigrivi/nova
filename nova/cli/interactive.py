import asyncio
import json
import os
import re
import shutil
import sys
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from nova.agent import AgentEvent
from nova.agent import Agent
from nova.app import build_agent
from nova.cli.commands import CommandDispatcher, CommandRegistry, ParsedCommand
from nova.cli.completion import CommandCompleter
from nova.cli.prompt_blocks import render_user_prompt_history_block
from nova.settings import Settings, get_settings
from nova.cli.ui import (
    EscapeKeyMonitor,
    PromptToolkitInputUI,
)

log = logging.getLogger(__name__)


_accumulated_text: list[str] = []
_spinner_thread: Optional[threading.Thread] = None
_spinner_stop = threading.Event()
_spinner_started_at: Optional[float] = None
_spinner_last_render_width = 0
_spinner_message = "Thinking..."
_MAX_RENDERED_DIFF_LINES = 80


def _user_history_block_width() -> int:
    return max(shutil.get_terminal_size(fallback=(170, 24)).columns, 20)


@dataclass(frozen=True)
class PromptOption:
    label: str
    description: str


def _parse_ask_user_question(content: str) -> dict:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    question = payload.get("question")
    return question if isinstance(question, dict) else {}


def _render_question_prompt(question: dict) -> str:
    header = str(question.get("header", "")).strip()
    body = str(question.get("question", "")).strip()
    if header and body:
        return f"{header}\n{body}"
    return header or body


def parse_options(content: str) -> list[PromptOption]:
    """Parse ask_user tool content into selectable options."""
    question = _parse_ask_user_question(content)
    if not question:
        return []
    if str(question.get("input_type", "")).strip().lower() != "select":
        return []
    options = question.get("options")
    if not isinstance(options, list):
        return []
    return [
        PromptOption(
            label=str(option.get("label", "")).strip(),
            description=str(option.get("description", "")).strip(),
        )
        for option in options
        if isinstance(option, dict) and str(option.get("label", "")).strip()
    ]


def _stream_text(chunk: str) -> None:
    """Buffer chunk and print directly for stable terminal scrollback."""
    _accumulated_text.append(chunk)
    print(chunk, end="", flush=True)


def _flush_stream() -> None:
    """Commit buffered text to screen."""
    had_output = bool(_accumulated_text)
    _accumulated_text.clear()
    if had_output:
        print()


def _render_tool_call(tc: object) -> str:
    name = tc.name if hasattr(tc, "name") else str(tc)
    arguments = tc.arguments if hasattr(tc, "arguments") else ""
    bullet = "\033[32m•\033[0m"
    title = f"\033[1m{name}\033[0m"
    if not arguments:
        return f"{bullet} {title}"

    compact_args = str(arguments)
    try:
        compact_args = json.dumps(
            json.loads(compact_args),
            ensure_ascii=False,
            separators=(", ", ": "),
        )
    except (TypeError, ValueError):
        pass
    compact_args = " ".join(compact_args.split())
    if len(compact_args) > 140:
        compact_args = compact_args[:137] + "..."
    args_line = f"\033[2;37m{compact_args}\033[0m"
    return f"{bullet} {title}\n  {args_line}"


def _render_history_message(role: object, content: object) -> Optional[str]:
    if not isinstance(role, str) or not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped:
        return None

    normalized_role = role.strip().lower()
    if normalized_role == "user":
        return render_user_prompt_history_block(
            submitted_text=stripped,
            prompt_label="❯ ",
            width=_user_history_block_width(),
        )
    if normalized_role in {"assistant", "system"}:
        return stripped
    return f"{role.strip().title() or 'Message'}: {stripped}"


def _print_history_transcript(messages: list[object]) -> None:
    rendered_messages = []
    for message in messages:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        rendered = _render_history_message(role, content)
        if rendered:
            rendered_messages.append(rendered)

    if not rendered_messages:
        return

    print()
    for index, rendered in enumerate(rendered_messages):
        if index > 0:
            print()
        print(rendered)
    print()


def _render_diff_block(text: str) -> str:
    lines = text.splitlines()
    if len(lines) > _MAX_RENDERED_DIFF_LINES:
        hidden = len(lines) - _MAX_RENDERED_DIFF_LINES
        lines = lines[:_MAX_RENDERED_DIFF_LINES]
        lines.append(f"... ({hidden} more diff lines not shown)")

    rendered: list[str] = []

    for line in lines:
        if line.startswith(("--- ", "+++ ")):
            rendered.append(f"\033[1;36m{line}\033[0m")
        elif line.startswith("@@"):
            rendered.append(f"\033[1;33m{line}\033[0m")
        elif line.startswith("+") and not line.startswith("+++ "):
            rendered.append(f"\033[32m{line}\033[0m")
        elif line.startswith("-") and not line.startswith("--- "):
            rendered.append(f"\033[31m{line}\033[0m")
        else:
            rendered.append(line)

    return "\n".join(rendered)


def _render_tool_result(tool_name: object, content: object) -> Optional[str]:
    if not isinstance(tool_name, str) or not isinstance(content, str):
        return None

    normalized_name = tool_name.strip().lower()
    if normalized_name not in {"edit", "write"}:
        return None

    stripped = content.strip()
    if not stripped:
        return None

    if "\n--- " in content and "\n+++ " in content and "\n@@ " in content:
        headline, _, diff_body = stripped.partition("\n\n")
        rendered_diff = _render_diff_block(diff_body or headline)
        label = normalized_name.upper()
        title = f"\033[1;35m[{label} DIFF]\033[0m {headline}"
        return f"{title}\n{rendered_diff}"

    return stripped


def _looks_like_error_message(text: object) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    return lowered.startswith("error:")


def _parse_done_payload(payload: object) -> tuple[Optional[str], Optional[str]]:
    if isinstance(payload, dict):
        reason = payload.get("reason")
        content = payload.get("content")
        return (
            reason if isinstance(reason, str) else None,
            content if isinstance(content, str) else None,
        )
    if isinstance(payload, str):
        return None, payload
    return None, None


def _parse_error_payload(payload: object) -> tuple[Optional[str], Optional[str]]:
    if isinstance(payload, dict):
        reason = payload.get("reason")
        message = payload.get("message")
        return (
            reason if isinstance(reason, str) else None,
            message if isinstance(message, str) else None,
        )
    if isinstance(payload, str):
        return None, payload
    return None, None


def _run_spinner() -> None:
    global _spinner_last_render_width
    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    idx = 0
    while not _spinner_stop.is_set():
        frame = chars[idx % len(chars)]
        elapsed = 0.0 if _spinner_started_at is None else max(
            0.0, time.monotonic() - _spinner_started_at)
        line = (
            f"\033[1;97m{frame} {_spinner_message}\033[0m "
            f"\033[97m{int(elapsed)}s\033[0m "
            f"\033[37m• Esc to interrupt\033[0m "
        )
        _spinner_last_render_width = len(line)
        sys.stderr.write(f"\r{line}")
        sys.stderr.flush()
        idx += 1
        _spinner_stop.wait(0.1)


def _stop_spinner() -> None:
    global _spinner_thread, _spinner_started_at, _spinner_last_render_width
    if _spinner_thread is None:
        return
    _spinner_stop.set()
    _spinner_thread.join(timeout=1)
    _spinner_thread = None
    _spinner_started_at = None
    clear_width = max(_spinner_last_render_width, 1)
    sys.stderr.write("\r" + (" " * clear_width) + "\r")
    sys.stderr.flush()
    _spinner_last_render_width = 0


def _start_spinner(message: str) -> None:
    global _spinner_thread, _spinner_started_at, _spinner_last_render_width, _spinner_message
    if _spinner_thread is not None and _spinner_thread.is_alive():
        if _spinner_message == message:
            return
        _stop_spinner()
    _spinner_message = message
    _spinner_started_at = time.monotonic()
    _spinner_last_render_width = 0
    _spinner_stop.clear()
    _spinner_thread = threading.Thread(target=_run_spinner, daemon=True)
    _spinner_thread.start()


def _start_llm_spinner() -> None:
    _start_spinner("Thinking...")


def _start_tool_spinner(tool_name: str) -> None:
    _start_spinner(f"Running {tool_name}...")


def _exit_process(code: int = 130) -> None:
    """Terminate the process immediately after flushing terminal output."""
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


class NovaCLI:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        log.info(
            f"Initializing NovaCLI with provider={self.settings.provider}, model={self.settings.model}")
        self.agent = build_agent(settings=self.settings)
        self._command_registry = CommandRegistry()
        self._command_dispatcher = CommandDispatcher(
            registry=self._command_registry,
            handlers={
                "quit": self._handle_quit_command,
                "new": self._handle_new_command,
                "clear": self._handle_clear_command,
                "sessions": self._handle_sessions_command,
                "load": self._handle_load_command,
            },
        )

        self._input_ui = PromptToolkitInputUI(
            completer=CommandCompleter(
                self._command_registry,
                load_candidates_provider=self._get_load_completion_candidates,
            )
        )
        self._running = False
        self._current_session_id = None
        self._pending_input: Optional[dict] = None
        self._streaming = False
        self._stop_requested = False
        self._stream_cancel_monitor: Optional[EscapeKeyMonitor] = None

    def _ensure_command_runtime(self) -> None:
        if not hasattr(self, "_command_registry"):
            self._command_registry = CommandRegistry()
        if not hasattr(self, "_command_dispatcher"):
            self._command_dispatcher = CommandDispatcher(
                registry=self._command_registry,
                handlers={
                    "quit": self._handle_quit_command,
                    "new": self._handle_new_command,
                    "clear": self._handle_clear_command,
                    "sessions": self._handle_sessions_command,
                    "load": self._handle_load_command,
                },
            )

    def _get_load_completion_candidates(self) -> list[dict]:
        sessions = getattr(self, "_cached_sessions", None)
        if not isinstance(sessions, list):
            return []
        return [session for session in sessions if isinstance(session, dict)]

    async def _show_sessions(self) -> None:
        """Show all sessions."""
        from nova.db.database import ensure_db
        db = await ensure_db()
        sessions = await db.get_all_sessions()

        if not sessions:
            self._show_info("No sessions found")
            return

        self._show_info(f"Sessions ({len(sessions)} total)")
        self._cached_sessions = sessions
        for i, sess in enumerate(sessions, 1):
            title = sess.get('title') or 'Untitled'
            is_active = sess['id'] == self._current_session_id
            marker = " (active)" if is_active else ""
            updated = sess.get('updated_at', 0) // 1000
            from datetime import datetime
            time_str = datetime.fromtimestamp(
                updated).strftime('%Y-%m-%d %H:%M')
            self._show_info(f"  {i}. {title}{marker}")
            self._show_info(f"      {sess['id'][:8]}... - {time_str}")

        self._show_info("Type /load <n> to load a session")

    async def _load_session(self, idx: int) -> None:
        """Load a session by index."""
        if not hasattr(self, '_cached_sessions') or idx < 0 or idx >= len(self._cached_sessions):
            self._show_info("Invalid session index")
            return

        sess = self._cached_sessions[idx]
        session_id = sess["id"]
        loaded = await self.agent.session.load_session(session_id)
        if loaded is None:
            self._show_error("Failed to load session")
            return

        from nova.db.database import ensure_db

        db = await ensure_db()
        history = await db.get_history_messages(session_id)
        self._current_session_id = session_id
        title = sess.get('title') or 'Untitled'
        self._show_info(f"Loaded session: {title}")
        if not history:
            self._show_info("No messages found")
            return
        _print_history_transcript(history)

    async def run_stream(self, user_input: str) -> None:
        log.info(
            f"Starting run_stream with session_id={self._current_session_id}")
        tool_calls_seen = []
        text_output_seen = False
        self._streaming = True
        self._stop_requested = False
        loop = asyncio.get_running_loop()
        self._stream_cancel_monitor = self._create_stream_cancel_monitor(
            lambda: loop.call_soon_threadsafe(self._request_stop)
        )
        self._stream_cancel_monitor.start()
        try:
            async for event, data in self.agent.chat_stream(user_input, session_id=self._current_session_id):
                if event == AgentEvent.TEXT_DELTA:
                    _stop_spinner()
                    text_output_seen = True
                    _stream_text(data)
                    continue
                elif event == AgentEvent.LLM_START:
                    log.info("LLM call started")
                    _start_llm_spinner()
                elif event == AgentEvent.LLM_END:
                    _stop_spinner()
                    _flush_stream()
                    log.info(f"Event: {event.value}")
                    continue
                log.info(f"Event: {event.value}, data type: {type(data)}")
                if event == AgentEvent.SESSION:
                    _flush_stream()
                    self._current_session_id = data
                    log.info(f"Session ID: {self._current_session_id}")
                elif event == AgentEvent.TOOL_CALL:
                    _stop_spinner()
                    _flush_stream()
                    tool_calls_seen.append(data)
                    tc_name = data.name if hasattr(data, 'name') else str(data)
                    print(_render_tool_call(data))
                    print()
                    log.info(f"Tool call: {tc_name}")
                    _start_tool_spinner(tc_name)
                elif event == AgentEvent.TOOL_RESULT:
                    _stop_spinner()
                    _flush_stream()
                    tool_name = data.get("tool")
                    result = data["result"]
                    content = result.content
                    if result.requires_input:
                        self._pending_input = {"content": content}
                    if not result.success and content:
                        self._show_error(content)
                    elif rendered := _render_tool_result(tool_name, content):
                        print(rendered)
                        print()
                    log.info(
                        f"Tool result tool={tool_name}, success={result.success}, content_len={len(content)}, requires_input={result.requires_input}")
                elif event == AgentEvent.DONE:
                    _stop_spinner()
                    _flush_stream()
                    reason, content = _parse_done_payload(data)
                    log.info(
                        f"DONE: tool_calls={len(tool_calls_seen)}, reason={reason}")
                    if reason == "stopped" or content == "Stopped by user":
                        self._show_error("Current run cancelled.")
                        return
                    if reason == "tool_failed":
                        if content:
                            self._show_error(content)
                        return
                    if _looks_like_error_message(content):
                        self._show_error(content)
                        return
                    if content and tool_calls_seen and not text_output_seen:
                        self._show_info(content)
                        return
                    if not content and not tool_calls_seen:
                        log.warning("Empty response with no tool calls")
                elif event == AgentEvent.ERROR:
                    _stop_spinner()
                    _flush_stream()
                    reason, message = _parse_error_payload(data)
                    log.info(f"ERROR: reason={reason}")
                    if message:
                        self._show_error(message)
                    return
        finally:
            if self._stream_cancel_monitor is not None:
                self._stream_cancel_monitor.stop()
                self._stream_cancel_monitor = None
            _flush_stream()
            self._streaming = False
            log.info("run_stream completed")

    def _create_stream_cancel_monitor(self, on_escape) -> EscapeKeyMonitor:
        if self._input_ui is not None:
            return self._input_ui.create_escape_monitor(on_escape)
        return EscapeKeyMonitor(on_escape)

    def _request_stop(self) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
        _stop_spinner()
        self.agent.interrupt()
        log.info("Escape pressed - stop requested for current run")

    def _show_info(self, text: str) -> None:
        print(f"\n{text}")

    def _show_error(self, text: str) -> None:
        self._show_info(f"\033[31m{text}\033[0m")

    async def _prompt_chat(self) -> str:
        if self._input_ui is not None:
            return await self._input_ui.prompt("❯ ")
        return await asyncio.to_thread(input, "\n\033[36mnova\033[0m ❯ ")

    async def _prompt_followup(self, content: str) -> str:
        if self._input_ui is not None:
            return await self._input_ui.prompt("❯ ", body=content)
        return await asyncio.to_thread(input, f"\n{content}\n> ")

    async def _handle_quit_command(self, command: ParsedCommand) -> bool:
        print("Bye.")
        log.info("User requested exit")
        self._running = False
        _exit_process(0)
        return True

    async def _handle_new_command(self, command: ParsedCommand) -> bool:
        self._current_session_id = None
        return True

    async def _handle_clear_command(self, command: ParsedCommand) -> bool:
        return True

    async def _handle_sessions_command(self, command: ParsedCommand) -> bool:
        await self._show_sessions()
        return True

    async def _handle_load_command(self, command: ParsedCommand) -> bool:
        if not command.args:
            self._show_error("Usage: /load <n>")
            return True
        try:
            idx = int(command.args) - 1
        except ValueError:
            self._show_error("Usage: /load <n>")
            return True
        await self._load_session(idx)
        return True

    async def run(self) -> None:
        self._ensure_command_runtime()
        sys.stdout.write("\033[?25h")
        print("Nova CLI")
        print("Type 'exit' or 'quit' to leave.")
        print(self._command_registry.banner_text())
        print()
        log.info("CLI started, entering main loop")
        self._running = True

        while self._running:
            try:
                if self._pending_input:
                    content = self._pending_input["content"]
                    question = _parse_ask_user_question(content)
                    if not question:
                        self._pending_input = None
                        self._show_error("Invalid ask_user payload.")
                        continue
                    options = parse_options(content)
                    if options:
                        question = _render_question_prompt(
                            question
                        ) or "Please select an option"
                        user_input = self._present_options(
                            question, options)
                    else:
                        prompt_body = _render_question_prompt(
                            question
                        )
                        user_input = await self._prompt_followup(prompt_body)
                    self._pending_input = None
                    print()
                    await self.run_stream(user_input)
                    print()
                    continue

                log.info("Waiting for user input...")
                user_input = await self._prompt_chat()
                user_input = user_input.strip()
                log.info(f"User input received: {user_input[:50]}...")
                if not user_input:
                    continue

                if await self._command_dispatcher.dispatch(user_input):
                    continue
                print()
                await self.run_stream(user_input)
                print()

            except EOFError:
                log.info("EOF received")
                break
            except KeyboardInterrupt:
                if self._streaming:
                    self.agent.interrupt()
                _flush_stream()
                _stop_spinner()
                self._running = False
                print("\nInterrupted. Exiting.")
                log.info("Keyboard interrupt - exiting CLI")
                _exit_process(130)
            except SystemExit:
                if self._streaming:
                    self.agent.interrupt()
                _flush_stream()
                _stop_spinner()
                self._running = False
                log.info("SystemExit raised - exiting CLI")
                _exit_process(130)
            except Exception as e:
                log.error(f"Error: {e}", exc_info=True)
                print(f"Error: {e}")

        log.info("CLI loop ended")

    def _present_options(self, question: str, options: list[PromptOption]) -> str:
        from rich.prompt import Prompt

        print(f"\n{question}\n")
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt.label} - {opt.description}")
        print()

        while True:
            try:
                choice = Prompt.ask("Select option", default="1")
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return options[idx].label
                print(f"Invalid choice. Please select 1-{len(options)}")
            except ValueError:
                print("Please enter a number")


async def main():
    from nova.cli.main import run_cli

    settings = get_settings()
    await run_cli(settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
