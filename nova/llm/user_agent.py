"""How Nova identifies itself to the providers it calls.

Every outbound provider request carries a ``User-Agent`` naming the product and
its version, so an upstream operator can tell a Nova request apart from a bare
SDK one -- the SDKs either send nothing or send their own token, and "Python/3.14
aiohttp/3.12" tells support nothing about who is calling.

The shape is the one the CLI agents converged on: ``<product>/<version> (<os>;
<arch>)``. It is a stable token a log line or a WAF rule can match, and it
carries no per-install identifier, so it cannot be used to track a machine.

The value is code-owned: it is written last, so neither ``options.headers`` nor
a request hook can replace it with another client's name. A provider that needs
a gateway's own token still gets it through ``headers``/``request_hook``; only
the identity header is not negotiable.
"""

from __future__ import annotations

import platform


def default_user_agent() -> str:
    """The ``User-Agent`` Nova sends unless a provider config overrides it."""
    # Imported here: nova/__init__ pulls in the agent, which pulls in the
    # providers, so a module-level import of the version would cycle.
    from nova import __version__

    system = platform.system().lower() or "unknown"
    machine = platform.machine().lower() or "unknown"
    return f"nova/{__version__} ({system}; {machine})"
