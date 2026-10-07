"""One HTTP call, and one place that decides what a failure means.

The backends differ in what they send and how they answer, but they do not
differ in what counts as a rate limit, a timeout, or an unusable reply. Keeping
that classification here means a new backend cannot invent its own notion of
these, and the caller sees one error vocabulary across the whole ring.
"""

from __future__ import annotations

import httpx

from nova.tools.web_search.base import (
    BackendResponse,
    SearchBackend,
    SearchBackendError,
)

REQUEST_TIMEOUT_SECONDS = 30.0

QUOTA_HEADER = "x-ratelimit-remaining"


async def call_backend(
    client: httpx.AsyncClient,
    backend: SearchBackend,
    query: str,
    limit: int,
) -> BackendResponse:
    """Run one search against *backend*.

    Args:
        client: Shared HTTP client.
        backend: Backend to call.
        query: The search query.
        limit: Requested result count.

    Returns:
        The result rows, empty when nothing matched, plus any reported
        remaining quota.

    Raises:
        SearchBackendError: On any transport, status, or payload failure.
    """
    request = backend.request(query, limit)

    try:
        response = await client.post(
            request.url, headers=request.headers, json=request.body
        )
    except httpx.TimeoutException as exc:
        raise SearchBackendError(f"{backend.name} timed out", "timeout") from exc
    except httpx.HTTPError as exc:
        # Name the exception type: httpx transport errors frequently carry an
        # empty str(), which would otherwise render as a bare message.
        raise SearchBackendError(
            f"{backend.name} request failed: {type(exc).__name__}", "transport"
        ) from exc

    if response.status_code == 429:
        raise SearchBackendError(
            f"{backend.name} rate limit reached (HTTP 429); the keyless free "
            "tier is capped",
            "rate_limited",
        )
    if response.status_code >= 400:
        # A backend that reports a rejection in the body knows more about what
        # went wrong than the status line does -- Keenable names the missing
        # parameter. Ask it before falling back to the status, and let a body
        # it cannot explain fall through rather than replace a clear status with
        # an unclear one.
        detail = backend.describe_error(response)
        raise SearchBackendError(
            f"{backend.name} returned HTTP {response.status_code}: {detail}"
            if detail
            else f"{backend.name} returned HTTP {response.status_code}",
            "http",
        )

    remaining = quota_remaining(response)
    return BackendResponse(backend.parse(response, limit), remaining)


def quota_remaining(response: httpx.Response) -> int | None:
    """Return the calls left in the window, when the backend reports it.

    Args:
        response: The HTTP response.

    Returns:
        The reported remaining count, or None when the header is absent or not
        a number. Never raises: a missing counter is not a failure.
    """
    raw = response.headers.get(QUOTA_HEADER)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
