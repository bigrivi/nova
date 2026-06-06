import asyncio
import shlex
import logging
from typing import Optional

from nova.app import build_agent
from nova.cli.commands import CommandDispatcher, CommandRegistry, ParsedCommand
from nova.cli.protocols import ChatStatus, UIAdapterProtocol

from nova.cli.ui import ModelGroup
from nova.cli.utils import exit_process as _exit_process
from nova.db.database import ensure_db
from nova.session import close_session_manager, get_session_manager
from nova.session.history_projection import get_user_visible_history
from nova.settings import get_settings, resolve_model_name, get_provider_name
from nova.constants import DEFAULT_AGENT_KEY
from nova.skills.service import SkillService
from nova.skills.installer import SkillInstallError

log = logging.getLogger(__name__)


class NovaCLI:
    """Main CLI orchestrator and StreamControlProtocol implementation."""

    def __init__(self, agent_key: str = DEFAULT_AGENT_KEY):
        self.settings = get_settings()
        self._agent_key = agent_key
        log.info(
            f"Initializing NovaCLI for agent '{agent_key}'")
        self.agent = None
        self._command_registry = CommandRegistry()
        self._command_dispatcher = CommandDispatcher(
            registry=self._command_registry,
            handlers={
                "quit": self._handle_quit_command,
                "new": self._handle_new_command,
                "clear": self._handle_clear_command,
                "models": self._handle_models_command,
                "theme": self._handle_theme_command,
                "install-skill": self._handle_install_skill_command,
                "install-global-skill": self._handle_install_global_skill_command,
                "list-agents": self._handle_list_agents_command,
                "create-agent": self._handle_create_agent_command,
                "delete-agent": self._handle_delete_agent_command,
                "sessions": self._handle_sessions_command,
                "child-status": self._handle_child_status_command,
            },
        )

        self._cached_sessions: list[dict] = []
        self.current_id: Optional[str] = None
        self._ui_adapter: Optional[UIAdapterProtocol] = None
        self._running = False
        self._pending_input: Optional[dict] = None
        self._streaming = False
        self._stop_requested = False
        self._exit_code: Optional[int] = None

    def get_session_id(self) -> Optional[str]:
        return self.current_id

    def set_session_id(self, session_id: Optional[str]) -> None:
        self.current_id = session_id

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

    @property
    def current_model_label(self) -> str:
        return self._current_model_label()

    @property
    def current_provider_label(self) -> str:
        return self._current_provider_label()

    def get_status(self) -> ChatStatus:
        return ChatStatus(
            model_label=self._current_model_label(),
            provider_label=self._current_provider_label(),
        )

    @property
    def command_registry(self) -> CommandRegistry:
        return self._command_registry

    @property
    def command_dispatcher(self) -> CommandDispatcher:
        return self._command_dispatcher

    @property
    def pending_input(self) -> Optional[dict]:
        return self._pending_input

    def reset_pending_input(self) -> None:
        self._pending_input = None

    def reset_stop_requested(self) -> None:
        self._stop_requested = False

    async def stream_chat_events(self, user_input: str):
        from nova.agent import AgentEvent

        self.reset_stop_requested()
        async for event, data in self.agent.chat_stream(
            user_input,
            session_id=self.current_id,
        ):
            if event == AgentEvent.SESSION:
                self.set_session_id(data if isinstance(data, str) else None)
            yield event, data

    def _current_model_label(self) -> str:
        if self.agent is None:
            return ""
        provider = self.agent.config.provider
        model = resolve_model_name(
            self.agent.config.model,
            self.settings.providers,
            provider_name=provider,
        ).strip()
        return model or "(server default)"

    def _current_provider_label(self) -> str:
        if self.agent is None:
            return ""
        return get_provider_name(self.settings.providers, self.agent.config.provider)

    def _model_groups(self) -> list[ModelGroup]:
        return [
            ModelGroup(provider=provider_name, models=list(
                provider_config.models.keys()))
            for provider_name, provider_config in self.settings.providers.items()
        ]

    def request_stop(self) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
        self.agent.interrupt()
        log.info("Escape pressed - stop requested for current run")

    async def _switch_model(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        import time
        db = await ensure_db()
        record = await db.get_agent(self._agent_key)
        if record:
            now = int(time.time() * 1000)
            await db.save_agent({
                "key": self._agent_key,
                "name": record["name"],
                "description": record.get("description", ""),
                "provider": provider or record["provider"],
                "model": model or record["model"],
                "tools": record.get("tools"),
                "workspace_dir": record.get("workspace_dir"),
                "created_at": record["created_at"],
                "updated_at": now,
            })

        self.agent = await build_agent(agent_key=self._agent_key,
                                       provider=provider, model=model)

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
        self.current_id = None
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
                    provider_branch = "└─" if group_index == len(
                        groups) - 1 else "├─"
                    model_indent = "   " if group_index == len(
                        groups) - 1 else "│  "
                    self._ui_adapter.show_info(
                        f"{provider_branch} {group.provider}")
                    self._ui_adapter.show_info(
                        f"{model_indent}No configured models")
            return True

        if self._ui_adapter is None:
            return True

        if self.agent:
            current_provider = self.agent.config.provider
            current_model = self.agent.config.model
        else:
            providers = self.settings.providers
            current_provider = list(providers.keys())[0] if providers else ""
            current_model = list(providers[current_provider].models.keys())[
                0] if providers and providers[current_provider].models else ""
        selection = await self._ui_adapter.prompt_model_selection(
            groups,
            current_provider=current_provider,
            current_model=current_model,
        )
        if selection is None:
            return True
        await self._switch_model(provider=selection.provider, model=selection.model)
        if self._ui_adapter:
            self._ui_adapter.show_info(
                f"Model switched to: {self._current_model_label()}")
            self._ui_adapter.update_status_bar()
        return True

    async def _handle_theme_command(self, command: ParsedCommand) -> bool:
        if self._ui_adapter is None:
            return True

        arg = command.args.strip()
        current = self._ui_adapter.current_theme_name()
        themes = self._ui_adapter.available_theme_names()

        if not arg:
            selected = await self._ui_adapter.prompt_theme_selection(
                themes,
                current_theme=current,
            )
            if selected is None:
                return True
            arg = selected

        if arg in {"current", "show"}:
            self._ui_adapter.show_info(f"Current theme: {current}")
            return True

        if arg in {"list", "ls"}:
            self._ui_adapter.show_info("Available themes: " + ", ".join(themes))
            return True

        if arg not in themes:
            self._ui_adapter.show_error(
                f"Unknown theme '{arg}'. Use /theme list to see available themes."
            )
            return True

        if self._ui_adapter.set_theme_name(arg):
            self._ui_adapter.show_info(f"Theme switched to: {arg}")
        else:
            self._ui_adapter.show_error(f"Failed to switch theme: {arg}")
        return True

    @staticmethod
    def _parse_install_skill_args(raw_args: str) -> tuple[str, bool]:
        try:
            tokens = shlex.split(raw_args)
        except ValueError as exc:
            raise SkillInstallError(
                f"Invalid install arguments: {exc}") from exc

        skill_ref = ""
        force = False
        for token in tokens:
            if token == "--force":
                force = True
                continue
            if token.startswith("-"):
                raise SkillInstallError(f"Unsupported option: {token}")
            if skill_ref:
                raise SkillInstallError(
                    "Usage: /install-skill <slug-or-url> [--force]")
            skill_ref = token

        if not skill_ref:
            raise SkillInstallError(
                "Usage: /install-skill <slug-or-url> [--force]")
        return skill_ref, force

    async def _handle_install_skill_command(self, command: ParsedCommand) -> bool:
        try:
            skill_ref, force = self._parse_install_skill_args(command.args)
            agent_key = self._agent_key
            if agent_key == DEFAULT_AGENT_KEY:
                skills_dir = self.settings.home / "skills"
            else:
                skills_dir = self.settings.home / "agents" / agent_key / "skills"
            service = SkillService(skills_dir=skills_dir)
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

    @staticmethod
    def _parse_install_global_skill_args(raw_args: str) -> tuple[str, bool]:
        try:
            tokens = shlex.split(raw_args)
        except ValueError as exc:
            raise SkillInstallError(
                f"Invalid install arguments: {exc}") from exc

        skill_ref = ""
        force = False
        for token in tokens:
            if token == "--force":
                force = True
                continue
            if token.startswith("-"):
                raise SkillInstallError(f"Unsupported option: {token}")
            if skill_ref:
                raise SkillInstallError(
                    "Usage: /install-global-skill <slug-or-url> [--force]")
            skill_ref = token

        if not skill_ref:
            raise SkillInstallError(
                "Usage: /install-global-skill <slug-or-url> [--force]")
        return skill_ref, force

    async def _handle_install_global_skill_command(self, command: ParsedCommand) -> bool:
        try:
            skill_ref, force = self._parse_install_global_skill_args(
                command.args)
            skills_dir = self.settings.home / "skills"
            service = SkillService(skills_dir=skills_dir)
            result = await service.install_global(skill_ref, force=force)
        except SkillInstallError as exc:
            if self._ui_adapter:
                self._ui_adapter.show_error(str(exc))
            return True

        action = "Updated" if result.replaced else "Installed"
        if self._ui_adapter:
            self._ui_adapter.show_info(
                f"{action} global skill '{result.skill_name}' at {result.installed_path}"
            )
        return True

    async def _handle_list_agents_command(self, command: ParsedCommand) -> bool:
        from nova.db.database import ensure_db
        db = await ensure_db()
        agents = await db.list_agents()
        if self._ui_adapter:
            await self._ui_adapter.prompt_agent_list(agents)
        return True

    async def _handle_create_agent_command(self, command: ParsedCommand) -> bool:
        if not self._ui_adapter:
            return True
        result = await self._ui_adapter.prompt_create_agent()
        if result is None:
            return True
        from nova.db.database import ensure_db
        db = await ensure_db()
        existing = await db.get_agent(result.key)
        if existing:
            self._ui_adapter.show_error(f"Agent '{result.key}' already exists")
            return True
        import time
        now = int(time.time() * 1000)
        await db.save_agent({
            "key": result.key,
            "name": result.name,
            "model": result.model,
            "provider": result.provider,
            "description": result.description,
            "tools": None,
            "workspace_dir": result.workspace_dir,
            "created_at": now,
            "updated_at": now,
        })
        if result.parent_ids:
            for parent_id in result.parent_ids:
                await db.add_agent_parent(result.key, parent_id)
        agent_dir = self.settings.home / "agents" / result.key
        agent_dir.mkdir(parents=True, exist_ok=True)
        self._ui_adapter.show_info(f"Agent '{result.key}' created")
        return True

    async def _handle_delete_agent_command(self, command: ParsedCommand) -> bool:
        if not self._ui_adapter:
            return True
        from nova.constants import DEFAULT_AGENT_KEY
        from nova.db.database import ensure_db
        import shutil
        db = await ensure_db()
        all_agents = await db.list_agents()
        deletable = [a for a in all_agents if a.get(
            "key") != DEFAULT_AGENT_KEY]
        if not deletable:
            self._ui_adapter.show_info("No agents to delete")
            return True
        key = await self._ui_adapter.prompt_delete_agent(deletable)
        if key is None:
            return True
        sessions = await db.get_all_sessions(agent_key=key, limit=99999)
        session_count = len(sessions)
        confirmed = await self._ui_adapter.prompt_delete_confirm(key, session_count)
        if not confirmed:
            return True
        await db.delete_agent(key)
        agent_dir = self.settings.home / "agents" / key
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        self._ui_adapter.show_info(f"Agent '{key}' and all its data deleted")
        return True

    async def _handle_sessions_command(self, command: ParsedCommand) -> bool:
        db = await ensure_db()
        sessions = await db.get_all_sessions()
        self._cached_sessions = [s for s in sessions if isinstance(s, dict)]
        if not self._cached_sessions:
            if self._ui_adapter:
                self._ui_adapter.show_info("No sessions found")
            return True
        if self._ui_adapter is None:
            return True

        selection = await self._ui_adapter.prompt_session_selection(
            self._cached_sessions,
            current_session_id=self.current_id,
        )
        if selection is None:
            return True
        await self._load_session_by_id(selection.session_id)
        return True

    async def _handle_child_status_command(self, command: ParsedCommand) -> bool:
        """Handle /child-status command to show child agent sessions."""
        from nova.session import get_session_manager
        
        session_manager = get_session_manager()
        current_session = session_manager.get_current_session()
        
        if not current_session:
            if self._ui_adapter:
                self._ui_adapter.show_error("No active session")
            return True
        
        child_sessions = await session_manager.get_child_sessions(current_session.id)
        
        if not child_sessions:
            if self._ui_adapter:
                self._ui_adapter.show_info("No child sessions found")
            return True
        
        sessions_data = [
            {
                "id": s.id,
                "agent_key": s.agent_key,
                "title": s.title,
                "message_count": s.message_count,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in child_sessions
        ]
        
        if self._ui_adapter:
            await self._ui_adapter.prompt_child_status(sessions_data, current_session.id)
        
        return True

    async def _load_session_by_id(self, session_id: str) -> None:
        if not self._cached_sessions:
            db = await ensure_db()
            sessions = await db.get_all_sessions()
            self._cached_sessions = [
                s for s in sessions if isinstance(s, dict)]
        sess = next(
            (s for s in self._cached_sessions if s.get("id") == session_id),
            None,
        )
        if sess is None:
            if self._ui_adapter:
                self._ui_adapter.error("Session not found")
            return

        loaded = await get_session_manager().load_session(session_id)
        if loaded is None:
            if self._ui_adapter:
                self._ui_adapter.error("Failed to load session")
            return

        db = await ensure_db()
        visible_history = await get_user_visible_history(db, session_id)
        self.current_id = session_id
        title = sess.get("title") or "Untitled"
        if self._ui_adapter:
            self._ui_adapter.info(f"Loaded session: {title}")
            if not visible_history:
                self._ui_adapter.info("No messages found")
            else:
                self._ui_adapter.print_history_transcript(visible_history)

    async def run(self, theme: str = "textual-dark") -> None:
        from nova.cli.chat_app import ChatApp

        app = ChatApp(controller=self, theme=theme)
        self._ui_adapter = app

        self.agent = await build_agent(agent_key=self._agent_key)
        self._cached_sessions = []

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

    await run_cli()


if __name__ == "__main__":
    asyncio.run(main())
