"""Parallel: a hosted MCP server that returns structured JSON.

Two things make Parallel its own dialect. It wants an *objective* plus a list of
search queries rather than a single query string, and it has no result-count
field at all -- it always answers with its own number of hits, so the requested
cap has to be applied here.

Its keyless tier also asks for a session identifier, used only to correlate rate
limiting within one quota window.

One measured quirk drives the description budget below: Parallel ships raw page
text rather than a curated summary, so a page with heavy navigation returns
boilerplate ("Keyboard shortcuts Press Escape to hide this help") that crowds
out the content within a small budget. The budget is deliberately tighter than
the other backends' for that reason.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from nova.settings import get_settings
from nova.tools.web_search.base import (
    SearchBackend,
    SearchBackendError,
    SearchHit,
    hits_to_rows,
    reject_non_object,
    require_hit_list,
)

#: Parallel's excerpts are page text, not summaries, so a navigation-heavy page
#: fills the budget with chrome. Measured against live responses, a longer
#: budget stops buying information.
DESCRIPTION_LIMIT = 240

#: Parallel asks for a session identifier purely to correlate rate limiting
#: within one free-tier quota window. It is generated per process and never
#: persisted, and no model or user identifier is sent alongside it.
PROCESS_SESSION_ID = uuid.uuid4().hex


class ParallelBackend(SearchBackend):
    """Parallel's hosted MCP server; structured JSON hits."""

    name = "parallel"
    url = "https://search.parallel.ai/mcp"
    tool_name = "web_search"
    description_limit = DESCRIPTION_LIMIT

    def api_key(self) -> str:
        """Return the configured Parallel key, empty when running keyless."""
        return get_settings().web_search.parallel_api_key

    def auth_headers(self, key: str) -> dict[str, str]:
        """Authenticate via a bearer token.

        Args:
            key: Parallel API key.

        Returns:
            Headers carrying the credential.
        """
        return {"Authorization": f"Bearer {key}"}

    def request_arguments(self, query: str, num_results: int) -> dict[str, Any]:
        """Build Parallel's search arguments.

        Args:
            query: The search query.
            num_results: Unused on the wire; this backend has no count field.

        Returns:
            Arguments for the ``web_search`` tool.
        """
        return {
            "objective": query,
            "search_queries": [query],
            "session_id": PROCESS_SESSION_ID,
        }

    def rows(self, text: str, limit: int) -> list[SearchHit]:
        """Build result rows from Parallel's JSON payload.

        Args:
            text: Payload text holding a JSON document.
            limit: Maximum rows to return.

        Returns:
            The rows, in the order Parallel ranked them.

        Raises:
            SearchBackendError: If the payload is not the expected JSON.
        """
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise SearchBackendError(
                f"{self.name} returned a payload that is not JSON", "payload"
            ) from exc
        reject_non_object(self.name, payload)
        hits = require_hit_list(self.name, payload)
        return hits_to_rows(self, hits, limit, ("description", "excerpts"))
