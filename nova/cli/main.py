"""
CLI entry helpers.
"""

from __future__ import annotations

from nova.cli import NovaCLI
from nova.settings import Settings, get_settings


async def run_cli(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    cli = NovaCLI(settings=settings)
    await cli.run()
