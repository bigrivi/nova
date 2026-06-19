"""
Nova - General-purpose agent system.

Launch command: python -m nova
"""

import asyncio
import argparse

from nova.cli.main import run_cli
from nova.desktop.main import run_desktop
from nova.server import run_server
from nova.settings import configure_logging, get_settings
from nova.tools.dependency_manager import init_site_packages


def main():
    parser = argparse.ArgumentParser(description="Nova CLI/Desktop agent runtime")
    settings = get_settings()
    provider_names = settings.provider_names or []
    parser.add_argument("mode", nargs="?", choices=["cli", "serve", "desktop"], default="cli",
                        help="Run mode: cli (terminal TUI), serve (HTTP backend), desktop (GUI window)")
    provider_default = provider_names[0] if provider_names else None
    parser.add_argument("--provider", "-p", choices=provider_names, default=provider_default,
                        help="LLM provider alias (default: first configured provider)")
    parser.add_argument("--model", "-m", default=None,
                        help="Model name (default: per-agent DB config)")
    from nova.constants import DEFAULT_AGENT_KEY
    parser.add_argument("--agent", default=DEFAULT_AGENT_KEY,
                        help=f"Agent key (default: {DEFAULT_AGENT_KEY})")
    parser.add_argument("--dev", action="store_true",
                        help="[desktop] Load frontend from Vite dev server (http://localhost:5173) instead of built-in server")
    parser.add_argument("--theme", default="textual-dark",
                        help="Textual theme to use (default: textual-dark)")
    parser.add_argument("--opentui", action="store_true",
                        help="Use experimental opentui-based chat instead of Textual")
    args = parser.parse_args()
    init_site_packages()
    configure_logging(settings)
    if args.mode == "serve":
        asyncio.run(run_server(settings=settings))
        return

    if args.mode == "desktop":
        run_desktop(settings=settings, dev=args.dev)
        return

    if args.opentui:
        from nova.opentui_app.chat_app import ChatApp
        asyncio.run(ChatApp().run())
        return

    asyncio.run(run_cli(agent_key=args.agent, theme=args.theme))


if __name__ == "__main__":
    main()
