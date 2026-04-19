import asyncio
import json
import os
import re
import sys
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from nova.agent import AgentEvent
from nova.app import AgentRuntime, build_runtime
from nova.settings import Settings, get_settings
from nova.cli.ui import EscapeKeyMonitor, PROMPT_TOOLKIT_AVAILABLE, PromptToolkitInputUI

log = logging.getLogger(__name__)


_accumulated_text: list[str] = []
_spinner_thread: Optional[threading.Thread] = None
_spinner_stop = threading.Event()
_spinner_started_at: Optional[float] = None
_spinner_last_render_width = 0


COMMANDS = [
    {"id": "new", "label": "New Session", "description": "Start a new conversation"},
    {"id": "sessions", "label": "Sessions", "description": "Show all sessions"},
    {"id": "clear", "label": "Clear", "description": "Clear the screen"},
    {"id": "quit", "label": "Quit", "description": "Exit the application"},
]


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


def _looks_like_error_message(text: object) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    return lowered.startswith("error:")


def _run_spinner() -> None:
    global _spinner_last_render_width
    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    idx = 0
    while not _spinner_stop.is_set():
        frame = chars[idx % len(chars)]
        elapsed = 0.0 if _spinner_started_at is None else max(
            0.0, time.monotonic() - _spinner_started_at)
        line = (
            f"\033[1;97m{frame} Thinking...\033[0m "
            f"\033[97m{int(elapsed)}s\033[0m "
            f"\033[37m• Esc to interrupt\033[0m "
        )
        _spinner_last_render_width = len(line)
        sys.stderr.write(f"\r{line}")
        sys.stderr.flush()
        idx += 1
        _spinner_stop.wait(0.1)


def _start_spinner() -> None:
    global _spinner_thread, _spinner_started_at, _spinner_last_render_width
    if _spinner_thread is not None and _spinner_thread.is_alive():
        return
    _spinner_started_at = time.monotonic()
    _spinner_last_render_width = 0
    _spinner_stop.clear()
    _spinner_thread = threading.Thread(target=_run_spinner, daemon=True)
    _spinner_thread.start()


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
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o",
        provider: str = "openai",
        settings: Optional[Settings] = None,
        runtime: Optional[AgentRuntime] = None,
    ):
        self.settings = settings or get_settings()
        self.runtime = runtime
        log.info(
            f"Initializing NovaCLI with provider={provider}, model={model}, base_url={base_url}")
        if self.runtime is None:
            runtime_provider = provider
            runtime_model = model
            if api_key is not None or base_url is not None:
                runtime_provider = provider
                runtime_model = model
            self.runtime = build_runtime(
                provider=runtime_provider,
                model=runtime_model,
                settings=self.settings,
            )

        self.agent = self.runtime.agent

        self._input_ui = PromptToolkitInputUI() if PROMPT_TOOLKIT_AVAILABLE else None
        self._running = False
        self._current_session_id = None
        self._pending_input: Optional[dict] = None
        self._streaming = False
        self._stop_requested = False
        self._stream_cancel_monitor: Optional[EscapeKeyMonitor] = None

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
        self._current_session_id = sess['id']
        title = sess.get('title') or 'Untitled'
        self._show_info(f"Loaded session: {title}")

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
                    text_output_seen = True
                    _stream_text(data)
                    continue
                elif event == AgentEvent.LLM_OUTPUT:
                    _stop_spinner()
                    log.info(f"Event: {event.value}")
                    continue
                elif event == AgentEvent.LLM_END:
                    _stop_spinner()
                    _flush_stream()
                    log.info(f"Event: {event.value}")
                    continue
                elif event == AgentEvent.STREAM_END:
                    _flush_stream()
                    log.info(f"Event: {event.value}")
                    continue
                log.info(f"Event: {event.value}, data type: {type(data)}")
                if event == AgentEvent.SESSION:
                    _flush_stream()
                    self._current_session_id = data
                    log.info(f"Session ID: {self._current_session_id}")
                elif event == AgentEvent.LLM_START:
                    log.info("LLM call started")
                    _start_spinner()
                elif event == AgentEvent.TOOL_CALL:
                    _flush_stream()
                    tool_calls_seen.append(data)
                    tc_name = data.name if hasattr(data, 'name') else str(data)
                    print(_render_tool_call(data))
                    print()
                    log.info(f"Tool call: {tc_name}")
                elif event == AgentEvent.TOOL_RESULT:
                    _flush_stream()
                    result = data["result"]
                    content = result.content
                    if result.requires_input:
                        self._pending_input = {"content": content}
                    if not result.success and content:
                        self._show_error(content)
                    log.info(
                        f"Tool result success={result.success}, content_len={len(content)}, requires_input={result.requires_input}")
                elif event == AgentEvent.RESPONSE:
                    log.info(f"RESPONSE: {data[:100] if data else 'empty'}")
                elif event == AgentEvent.DONE:
                    _stop_spinner()
                    _flush_stream()
                    log.info(
                        f"DONE: tool_calls={len(tool_calls_seen)}")
                    if data == "Stopped by user":
                        self._show_error("Current run cancelled.")
                        return
                    if _looks_like_error_message(data):
                        self._show_error(data)
                        return
                    if data and tool_calls_seen and not text_output_seen:
                        self._show_info(data)
                        return
                    if not data and not tool_calls_seen:
                        log.warning("Empty response with no tool calls")
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

    async def _handle_command(self, user_input: str) -> bool:
        if user_input.startswith('/'):
            cmd = user_input[1:]
            if cmd == "quit" or cmd == "q":
                print("Bye.")
                log.info("User requested exit")
                self._running = False
                _exit_process(0)
                return True
            elif cmd == "new":
                self._current_session_id = None
                return True
            elif cmd == "clear":
                return True
            elif cmd == "sessions":
                await self._show_sessions()
                return True
            elif cmd.startswith("load "):
                parts = cmd.split(" ", 1)
                if len(parts) == 2:
                    idx = int(parts[1]) - 1
                    await self._load_session(idx)
                return True
            return True

        if user_input.lower() in ("exit", "quit", "q"):
            print("Bye.")
            log.info("User requested exit")
            self._running = False
            _exit_process(0)
            return True

        return False

    async def run(self) -> None:
        sys.stdout.write("\033[?25h")
        print("Nova CLI")
        print("Type 'exit' or 'quit' to leave.")
        print("Use /new, /sessions, /load <n>, /clear, or /quit for commands.")
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

                if await self._handle_command(user_input):
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
    await run_cli(provider=settings.provider, model=settings.model, settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
