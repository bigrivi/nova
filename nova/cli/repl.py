import asyncio
import re
import shlex
import sys
import logging
from dataclasses import replace
from typing import Optional

from nova.app import build_agent
from nova.cli.commands import CommandDispatcher, CommandRegistry, ParsedCommand
from nova.cli.completion import CommandCompleter
from nova.cli.history_render import (
    PromptOption,
    parse_ask_user_question as _parse_ask_user_question,
    parse_options,
    render_question_prompt as _render_question_prompt,
)
from nova.cli.session_manager import SessionManager
from nova.cli.stream_controller import StreamController, StreamControlProtocol
from nova.cli.terminal_display import TerminalDisplay
from nova.cli.utils import exit_process as _exit_process
from nova.session import close_session_manager
from nova.settings import Settings, get_settings
from nova.skills import initialize_skill_service
from nova.skills.installer import SkillInstallError
from nova.cli.ui import (
    EscapeKeyMonitor,
    ModelGroup,
    PromptToolkitInputUI,
)

log = logging.getLogger(__name__)


class NovaCLI(StreamControlProtocol):
    """Main CLI orchestrator and StreamControlProtocol implementation."""
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
                "models": self._handle_models_command,
                "install-skill": self._handle_install_skill_command,
                "sessions": self._handle_sessions_command,
            },
        )

        self._input_ui = PromptToolkitInputUI(
            completer=CommandCompleter(self._command_registry),
            model_label_provider=self._current_model_label,
        )
        self._display = TerminalDisplay()
        self._running = False
        self._pending_input: Optional[dict] = None
        self._streaming = False
        self._stop_requested = False
        self._exit_code: Optional[int] = None
        self._session_manager = SessionManager(
            agent=self.agent,
            display=self._display,
        )

    def get_session_id(self) -> Optional[str]:
        return self._session_manager.current_id

    def set_session_id(self, session_id: Optional[str]) -> None:
        self._session_manager.current_id = session_id

    def set_pending_input(self, payload: dict) -> None:
        self._pending_input = payload

    def create_cancel_monitor(self, on_escape) -> EscapeKeyMonitor:
        if self._input_ui is not None:
            return self._input_ui.create_escape_monitor(on_escape)
        return EscapeKeyMonitor(on_escape)

    def _current_model_label(self) -> str:
        provider = self.settings.provider
        model = self.settings.resolve_model_name(
            self.settings.model,
            provider_name=provider,
        ).strip()
        return model or "(server default)"

    def _model_groups(self) -> list[ModelGroup]:
        return [
            ModelGroup(provider=provider_name, models=list(provider_config.models.keys()))
            for provider_name, provider_config in self.settings.providers.items()
        ]

    def request_stop(self) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
        self._display.spinner.stop()
        self.agent.interrupt()
        log.info("Escape pressed - stop requested for current run")

    def _rebuild_runtime(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        updated_settings = replace(
            self.settings,
            provider=self.settings.provider if provider is None else provider,
            model=self.settings.model if model is None else model,
        )
        self.settings = updated_settings
        self.agent = build_agent(settings=self.settings)
        self._session_manager.set_agent(self.agent)

    async def run_stream(self, user_input: str) -> None:
        self._streaming = True
        self._stop_requested = False
        controller = StreamController(
            agent=self.agent,
            spinner=self._display.spinner,
            render=self._display,
            control=self,
        )
        try:
            await controller.run(user_input)
        finally:
            self._streaming = False

    def _shutdown(self, *, message: Optional[str] = None) -> None:
        if self._streaming:
            self.agent.interrupt()
        self._display.flush()
        self._display.spinner.stop()
        self._running = False
        if message:
            print(message)

    async def _prompt_chat(self) -> str:
        if self._input_ui is not None:
            return await self._input_ui.prompt("❯ ")
        return await asyncio.to_thread(input, "\n\033[36mnova\033[0m ❯ ")

    async def _prompt_followup(self, content: str) -> str:
        if self._input_ui is not None:
            return await self._input_ui.prompt("❯ ", body=content)
        return await asyncio.to_thread(input, f"{content}\n\n> ")

    async def _handle_quit_command(self, command: ParsedCommand) -> bool:
        print("Bye. 👋")
        log.info("User requested exit")
        self._running = False
        self._exit_code = 0
        return True

    async def _cleanup_runtime(self) -> None:
        try:
            await close_session_manager()
        except Exception:
            log.exception("Failed to close session manager")

    async def _handle_new_command(self, command: ParsedCommand) -> bool:
        self._session_manager.reset()
        return True

    def _print_banner(self) -> None:
        print("Nova CLI")
        print("Type 'exit' or 'quit' to leave.")
        print(self._command_registry.banner_text())
        print()

    async def _handle_clear_command(self, command: ParsedCommand) -> bool:
        self._display.clear_terminal()
        self._print_banner()
        return True

    async def _handle_models_command(self, command: ParsedCommand) -> bool:
        groups = self._model_groups()
        if not any(group.models for group in groups):
            self._display.info("Configured models:")
            for group_index, group in enumerate(groups):
                provider_branch = "└─" if group_index == len(groups) - 1 else "├─"
                model_indent = "   " if group_index == len(groups) - 1 else "│  "
                self._display.info(f"\033[1m{provider_branch} {group.provider}\033[0m")
                self._display.info(f"{model_indent}No configured models")
            return True

        if self._input_ui is None:
            self._display.info("Interactive model selection requires prompt_toolkit input.")
            return True

        selection = await self._input_ui.prompt_model_selection(
            groups,
            current_provider=self.settings.provider,
            current_model=self.settings.model,
        )
        if selection is None:
            return True
        self._rebuild_runtime(provider=selection.provider, model=selection.model)
        self._display.info(f"Model switched to: {self._current_model_label()}")
        return True

    @staticmethod
    def _parse_install_skill_args(raw_args: str) -> tuple[str, bool]:
        try:
            tokens = shlex.split(raw_args)
        except ValueError as exc:
            raise SkillInstallError(f"Invalid install arguments: {exc}") from exc

        skill_ref = ""
        force = False
        for token in tokens:
            if token == "--force":
                force = True
                continue
            if token.startswith("-"):
                raise SkillInstallError(f"Unsupported option: {token}")
            if skill_ref:
                raise SkillInstallError("Usage: /install-skill <slug-or-url> [--force]")
            skill_ref = token

        if not skill_ref:
            raise SkillInstallError("Usage: /install-skill <slug-or-url> [--force]")
        return skill_ref, force

    async def _handle_install_skill_command(self, command: ParsedCommand) -> bool:
        try:
            skill_ref, force = self._parse_install_skill_args(command.args)
            service = initialize_skill_service(settings=self.settings)
            result = await service.install_from_clawhub(skill_ref, force=force)
        except SkillInstallError as exc:
            self._display.error(str(exc))
            return True

        action = "Updated" if result.replaced else "Installed"
        self._display.info(
            f"{action} skill '{result.skill_name}' at {result.installed_path}"
        )
        return True

    async def _handle_sessions_command(self, command: ParsedCommand) -> bool:
        sessions = await self._session_manager.list_sessions()
        if not sessions:
            self._display.info("No sessions found")
            return True
        if self._input_ui is None:
            await self._session_manager.show_sessions()
            return True

        selection = await self._input_ui.prompt_session_selection(
            sessions,
            current_session_id=self._session_manager.current_id,
        )
        if selection is None:
            return True
        await self._session_manager.load_session_by_id(selection.session_id)
        return True

    async def _handle_pending_input_turn(self) -> bool:
        if not self._pending_input:
            return False
        content = self._pending_input["content"]
        question = _parse_ask_user_question(content)
        if not question:
            self._pending_input = None
            self._display.error("Invalid ask_user payload.")
            return True
        options = parse_options(content)
        if options:
            prompt_text = _render_question_prompt(question) or "Please select an option"
            user_input = self._present_options(prompt_text, options)
        else:
            prompt_body = _render_question_prompt(question)
            user_input = await self._prompt_followup(prompt_body)
        self._pending_input = None
        self._display.print_user_message(user_input)
        await self.run_stream(user_input)
        print()
        return True

    async def _handle_user_turn(self) -> None:
        log.info("Waiting for user input...")
        user_input = await self._prompt_chat()
        user_input = user_input.strip()
        log.info(f"User input received: {user_input[:50]}...")
        if not user_input:
            return

        if await self._command_dispatcher.dispatch(user_input):
            return
        self._display.print_user_message(user_input)
        await self.run_stream(user_input)
        print()

    async def run(self) -> None:
        sys.stdout.write("\033[?25h")
        self._print_banner()
        log.info("CLI started, entering main loop")
        self._running = True
        self._exit_code = None

        try:
            while self._running:
                try:
                    if await self._handle_pending_input_turn():
                        continue
                    await self._handle_user_turn()

                except EOFError:
                    log.info("EOF received")
                    break
                except KeyboardInterrupt:
                    log.info("Keyboard interrupt - exiting CLI")
                    self._shutdown(message="\nInterrupted. Exiting.")
                    self._exit_code = 130
                    break
                except SystemExit:
                    log.info("SystemExit raised - exiting CLI")
                    self._shutdown()
                    self._exit_code = 130
                    break
                except Exception as e:
                    log.error(f"Error: {e}", exc_info=True)
                    print(f"Error: {e}")
        finally:
            await self._cleanup_runtime()
            log.info("CLI loop ended")
            if self._exit_code is not None:
                _exit_process(self._exit_code)

    def _present_options(self, question: str, options: list[PromptOption]) -> str:
        from rich.prompt import Prompt

        self._display.render_options_prompt(question, options)

        while True:
            try:
                choice = Prompt.ask("Select option", default="1")
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return options[idx].label
                self._display.error(f"Invalid choice. Please select 1-{len(options)}")
            except ValueError:
                self._display.error("Please enter a number")


async def main():
    from nova.cli.main import run_cli

    settings = get_settings()
    await run_cli(settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
