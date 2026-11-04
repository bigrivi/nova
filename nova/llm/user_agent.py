"""How Nova identifies itself to the providers it calls.

Every outbound provider request carries a ``User-Agent`` naming the product and
its version, so an upstream operator can tell a Nova request apart from a bare
SDK one -- the SDKs either send nothing or send their own token, and "Python/3.14
aiohttp/3.12" tells support nothing about who is calling.

The shape is the one the CLI agents converged on: ``<product>/<version> (<os>;
<arch>)``. It is a stable token a log line or a WAF rule can match, and it
carries no per-install identifier, so it cannot be used to track a machine.

The default is code-owned and written last, so neither ``options.headers`` nor a
request hook can replace it by accident. A gateway that fingerprints its clients
is the one real exception, and it is opt-in per provider:
``options.user_agent`` changes the identity Nova presents to that provider only.
Discovery honours the same value, so the connect probe and every later request
arrive as the same client.
"""

from __future__ import annotations

import platform

from nova.version import __version__


def default_user_agent() -> str:
    """The ``User-Agent`` Nova sends unless a provider config overrides it."""
    system = platform.system().lower() or "unknown"
    machine = platform.machine().lower() or "unknown"
    return f"nova/{__version__} ({system}; {machine})"
