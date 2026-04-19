"""
Nova - General-purpose agent system.

Launch command: python -m nova
"""

import asyncio
import argparse
from dataclasses import replace

from nova.cli.main import run_cli
from nova.server import run_server
from nova.settings import Settings, configure_logging, get_settings


def _build_effective_settings(
    settings: Settings,
    provider: str,
    model: str | None,
) -> Settings:
    return replace(
        settings,
        provider=provider,
        model=settings.model if model is None else model,
    )


def main():
    parser = argparse.ArgumentParser(description="Nova CLI/Desktop agent runtime")
    settings = get_settings()
    provider_names = settings.provider_names or [settings.provider]
    parser.add_argument("mode", nargs="?", choices=["cli", "serve"], default="cli",
                        help="Run mode. 'serve' is reserved for future backend service mode.")
    parser.add_argument("--provider", "-p", choices=provider_names, default=settings.provider,
                        help="LLM provider alias from ~/.nova/config.json")
    parser.add_argument("--model", "-m", default=None,
                        help="Model name. Optional for OpenAI-compatible services that already fix the model server-side.")
    args = parser.parse_args()
    effective_settings = _build_effective_settings(
        settings=settings,
        provider=args.provider,
        model=args.model,
    )

    configure_logging(effective_settings)
    if args.mode == "serve":
        asyncio.run(run_server(settings=effective_settings))
        return

    asyncio.run(run_cli(settings=effective_settings))


if __name__ == "__main__":
    main()
