"""Keenable: plain REST, keyless, and the only backend that reports its quota.

Keenable is not an MCP server. It is a single JSON POST with no envelope and no
streaming, so it overrides the parse half of the backend protocol rather than
inheriting the hosted-MCP implementation. Two consequences are worth knowing:

* The keyless path requires an ``X-Keenable-Title`` attribution header naming
  the calling application, and rejects a request without one. No user or model
  identifier belongs in it.
* It answers with an ``x-ratelimit-remaining`` header. That is the only quota
  state Nova can see anywhere in the ring, and it is what settles whether the
  free pool is per-client or shared.

Its ``snippet`` is a real summary rather than a page dump, so it keeps more of
it than the backends that ship raw text.
"""

from __future__ import annotations

from typing import Any

import httpx

from nova.settings import get_settings
from nova.tools.web_search.base import (
    SearchBackend,
    SearchBackendError,
    SearchHit,
    SearchRequest,
    hits_to_rows,
    reject_non_object,
    require_hit_list,
)

#: Keenable's snippet is a curated summary, so a longer budget still buys
#: signal -- measured snippets run to a few thousand characters.
DESCRIPTION_LIMIT = 320


class KeenableBackend(SearchBackend):
    """Keenable's public REST search; keyless and quota-reporting."""

    name = "keenable"
    url = "https://api.keenable.ai/v1/search/public"
    authenticated_url = "https://api.keenable.ai/v1/search"
    search_mode = "pro"
    app_identifier = "nova"
    description_limit = DESCRIPTION_LIMIT

    def api_key(self) -> str:
        """Return the configured Keenable key, empty when running keyless."""
        return get_settings().web_search.keenable_api_key

    def request(self, query: str, num_results: int) -> SearchRequest:
        """Build Keenable's plain JSON request.

        The keyless endpoint requires the attribution header and rejects a
        request without it. A configured key switches to the authenticated
        path, which raises the caller's ceiling.

        Args:
            query: The search query.
            num_results: Unused; the endpoint has no count field.

        Returns:
            The request to send.
        """
        headers = {
            "content-type": "application/json",
            "X-Keenable-Title": self.app_identifier,
        }
        key = self.api_key()
        if key:
            headers["X-API-Key"] = key
            url = self.authenticated_url
        else:
            url = self.url
        return SearchRequest(url, headers, {"query": query, "mode": self.search_mode})

    def parse(self, response: httpx.Response, limit: int) -> list[SearchHit]:
        """Decode Keenable's directly returned JSON.

        Args:
            response: The HTTP response.
            limit: Maximum rows to return.

        Returns:
            The result rows.

        Raises:
            SearchBackendError: If the body is not JSON.
        """
        try:
            payload = response.json()
        except ValueError as exc:
            raise SearchBackendError(
                f"{self.name} returned a response that is not JSON", "payload"
            ) from exc
        return self.rows_from_payload(payload, limit)

    def rows_from_payload(self, payload: Any, limit: int = 0) -> list[SearchHit]:
        """Build result rows from an already-decoded Keenable payload.

        Keenable reports a rejected request in the body alongside a 4xx status,
        carrying an ``error`` code and a human-readable ``message``; both are
        surfaced so a bad parameter is not reported as a bare HTTP failure.

        Args:
            payload: Decoded response body.
            limit: Maximum rows to return; a non-positive value keeps them all.

        Returns:
            The rows, in the order Keenable ranked them.

        Raises:
            SearchBackendError: If the body is an error or lacks results.
        """
        reject_non_object(self.name, payload)
        if payload.get("error"):
            detail = payload.get("message") or payload["error"]
            raise SearchBackendError(
                f"{self.name} rejected the request: {detail}", "http"
            )
        hits = require_hit_list(self.name, payload)
        return hits_to_rows(self, hits, limit, ("description", "snippet"))
