"""
CLI entry helpers.
"""

from __future__ import annotations

from nova.cli import NovaCLI
from nova.constants import DEFAULT_AGENT_KEY


async def run_cli(agent_key: str = DEFAULT_AGENT_KEY, theme: str = "textual-dark") -> None:
    cli = NovaCLI(agent_key=agent_key)
    await cli.run(theme=theme)
