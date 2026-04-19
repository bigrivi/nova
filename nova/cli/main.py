"""
CLI entry helpers.
"""

from __future__ import annotations

from typing import Optional

from nova.app import build_runtime
from nova.cli import NovaCLI
from nova.settings import Settings, get_settings


async def run_cli(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> None:
    settings = settings or get_settings()
    runtime = build_runtime(provider=provider, model=model, settings=settings)
    cli = NovaCLI(runtime=runtime, settings=settings)
    await cli.run()
