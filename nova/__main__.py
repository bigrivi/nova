"""
Nova - General-purpose agent system.

Launch command: python -m nova
"""

import asyncio
import argparse

from nova.cli.main import run_cli
from nova.server import run_server
from nova.settings import configure_logging, get_settings


def main():
    parser = argparse.ArgumentParser(description="Nova CLI/Desktop agent runtime")
    settings = get_settings()
    parser.add_argument("mode", nargs="?", choices=["cli", "serve"], default="cli",
                        help="Run mode. 'serve' is reserved for future backend service mode.")
    parser.add_argument("--provider", "-p", choices=["openai", "ollama"], default=settings.provider,
                        help="LLM provider (default: env-configured provider)")
    parser.add_argument("--model", "-m", default=None,
                        help="Model name. Optional for OpenAI-compatible services that already fix the model server-side.")
    args = parser.parse_args()

    configure_logging(settings)
    if args.mode == "serve":
        asyncio.run(run_server(settings=settings))
        return

    asyncio.run(
        run_cli(
            provider=args.provider,
            model=args.model,
            settings=settings,
        )
    )


if __name__ == "__main__":
    main()
