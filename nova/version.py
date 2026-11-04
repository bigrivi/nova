"""The release number, in a module with no imports.

It lives here rather than in ``nova/__init__`` because the package ``__init__``
imports the agent, which imports the providers and the MCP client, and all of them
want to report the version: a module-level ``from nova import __version__`` in any
of those cycles. This module depends on nothing, so it is always safe to import.
"""

from __future__ import annotations

__version__ = "1.0.2"
