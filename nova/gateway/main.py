"""Gateway entry point: start every enabled adapter in one process."""

from __future__ import annotations

import asyncio
import logging

from nova.gateway.adapters import build_adapters
from nova.gateway.config import GatewayConfig, load_config
from nova.gateway.core import GatewayCore, NovaClient
from nova.gateway.platform import PlatformAdapter

log = logging.getLogger(__name__)


async def safe_start(adapter: PlatformAdapter) -> None:
    """Start one adapter; a failure is logged and never takes down the rest."""
    try:
        await adapter.start()
        log.info("gateway: %s started", adapter.name)
    except Exception as exc:
        log.warning("gateway: %s failed to start: %s", adapter.name, exc)


async def run(config: GatewayConfig) -> None:
    adapters = build_adapters(config)
    if not adapters:
        log.warning("gateway: no platforms enabled")
        return
    core = GatewayCore(
        nova=NovaClient(config.nova_url),
        adapters=adapters,
        allowed_senders=config.allowed_senders,
    )
    for adapter in adapters.values():
        adapter.on_message(
            lambda msg, platform=adapter.name: core.handle_inbound(platform, msg)
        )
    tasks = [asyncio.create_task(safe_start(adapter)) for adapter in adapters.values()]
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
        # Keep the process alive while adapters poll in the background.
        await asyncio.Event().wait()
    finally:
        for adapter in adapters.values():
            try:
                await adapter.stop()
            except Exception:
                pass


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(load_config()))


if __name__ == "__main__":
    main()
