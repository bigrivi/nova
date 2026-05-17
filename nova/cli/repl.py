import asyncio
import shlex
import logging
from dataclasses import replace
from typing import Optional

from nova.app import build_agent
from nova.cli.commands import CommandDispatcher, CommandRegistry, ParsedCommand
from nova.cli.session_manager import SessionManager
from nova.cli.stream_controller import StreamController, StreamControlProtocol
from nova.cli.ui import ModelGroup
from nova.cli.utils import exit_process as _exit_process
from nova.session import close_session_manager
from nova.settings import Settings, get_settings
from nova.skills import initialize_skill_service
from nova.skills.installer import SkillInstallError

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

        self._session_manager: Optional[SessionManager] = None
        self._ui_adapter: Optional[object] = None
        self._running = False
        self._pending_input: Optional[dict] = None
        self._streaming = False
        self._stop_requested = False
        self._exit_code: Optional[int] = None

    def get_session_id(self) -> Optional[str]:
        if self._session_manager is None:
            return None
        return self._session_manager.current_id

    def set_session_id(self, session_id: Optional[str]) -> None:
        if self._session_manager is None:
            return
        self._session_manager.current_id = session_id

    def set_pending_input(self, payload: dict) -> None:
        self._pending_input = payload

    def create_cancel_monitor(self, on_escape):
        if self._ui_adapter is not None:
            class _NoopMonitor:
                def start(self): pass
                def stop(self): pass
            return _NoopMonitor()
        from nova.cli.ui import EscapeKeyMonitor
        return EscapeKeyMonitor(on_escape)

    def _current_model_label(self) -> str:
        provider = self.settings.provider
        model = self.settings.resolve_model_name(
            self.settings.model,
            provider_name=provider,
        ).strip()
        return model or "(server default)"

    def _current_provider_label(self) -> str:
        provider = self.settings.provider
        if provider:
            provider_config = self.settings.get_provider_config(provider)
            if provider_config:
                return provider_config.name
        return ""

    def _model_groups(self) -> list[ModelGroup]:
        return [
            ModelGroup(provider=provider_name, models=list(provider_config.models.keys()))
            for provider_name, provider_config in self.settings.providers.items()
        ]

    def request_stop(self) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
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
        if self._session_manager:
            self._session_manager.set_agent(self.agent)

    async def run_stream(self, user_input: str, *, render, spinner=None) -> None:
        log.debug("run_stream: input_len=%d, render=%s", len(user_input), type(render).__name__)
        self._streaming = True
        self._stop_requested = False
        controller = StreamController(
            agent=self.agent,
            render=render,
            control=self,
        )
        try:
            await controller.run(user_input)
        finally:
            self._streaming = False
            log.debug("run_stream finished")

    def _shutdown(self, *, message: Optional[str] = None) -> None:
        if self._streaming:
            self.agent.interrupt()
        self._running = False
        if message:
            print(message)

    async def _handle_quit_command(self, command: ParsedCommand) -> bool:
        log.info("User requested exit")
        if self._ui_adapter:
            self._ui_adapter.shutdown()
        else:
            self._running = False
            self._exit_code = 0
        return True

    async def _cleanup_runtime(self) -> None:
        try:
            await close_session_manager()
        except Exception:
            log.exception("Failed to close session manager")

    async def _handle_new_command(self, command: ParsedCommand) -> bool:
        if self._session_manager:
            self._session_manager.reset()
        return True

    async def _handle_clear_command(self, command: ParsedCommand) -> bool:
        if self._ui_adapter:
            self._ui_adapter.clear_screen()
        return True

    async def _handle_models_command(self, command: ParsedCommand) -> bool:
        groups = self._model_groups()
        if not any(group.models for group in groups):
            if self._ui_adapter:
                self._ui_adapter.show_info("Configured models:")
                for group_index, group in enumerate(groups):
                    provider_branch = "└─" if group_index == len(groups) - 1 else "├─"
                    model_indent = "   " if group_index == len(groups) - 1 else "│  "
                    self._ui_adapter.show_info(f"{provider_branch} {group.provider}")
                    self._ui_adapter.show_info(f"{model_indent}No configured models")
            return True

        if self._ui_adapter is None:
            return True

        selection = await self._ui_adapter.prompt_model_selection(
            groups,
            current_provider=self.settings.provider,
            current_model=self.settings.model,
        )
        if selection is None:
            return True
        self._rebuild_runtime(provider=selection.provider, model=selection.model)
        if self._ui_adapter:
            self._ui_adapter.show_info(f"Model switched to: {self._current_model_label()}")
            self._ui_adapter.update_status_bar()
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
            if self._ui_adapter:
                self._ui_adapter.show_error(str(exc))
            return True

        action = "Updated" if result.replaced else "Installed"
        if self._ui_adapter:
            self._ui_adapter.show_info(
                f"{action} skill '{result.skill_name}' at {result.installed_path}"
            )
        return True

    async def _handle_sessions_command(self, command: ParsedCommand) -> bool:
        if self._session_manager is None:
            return True
        sessions = await self._session_manager.list_sessions()
        if not sessions:
            if self._ui_adapter:
                self._ui_adapter.show_info("No sessions found")
            return True
        if self._ui_adapter is None:
            return True

        selection = await self._ui_adapter.prompt_session_selection(
            sessions,
            current_session_id=self._session_manager.current_id,
        )
        if selection is None:
            return True
        await self._session_manager.load_session_by_id(selection.session_id)
        return True

    async def run(self) -> None:
        from nova.cli.chat_app import ChatApp

        app = ChatApp(nova_cli=self)
        self._ui_adapter = app

        self._session_manager = SessionManager(
            agent=self.agent,
            display=app,
        )

        log.info("Textual chat app starting...")
        self._running = True
        self._exit_code = None

        try:
            await app.run_async()
        except SystemExit:
            log.info("SystemExit raised during app run")
        except Exception as e:
            log.error(f"Error during app run: {e}", exc_info=True)
        finally:
            await self._cleanup_runtime()
            log.info("Chat app ended")
            if self._exit_code is not None:
                _exit_process(self._exit_code)


async def main():
    from nova.cli.main import run_cli

    settings = get_settings()
    await run_cli(settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
