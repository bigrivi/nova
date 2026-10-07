"""Search the web over a keyless-first ring of public backends.

Search is a baseline capability, so every backend here works without a
credential and an API key is an optional upgrade that raises the caller's rate
ceiling rather than a prerequisite. Calls rotate across the ring so one
backend's free allowance is not the ceiling for the whole agent, and a backend
that fails -- rate limit, transport error, unusable payload -- hands the call to
its peer rather than surfacing a bare failure.

Two properties are load-bearing at this interface rather than inherited from the
parts:

* A backend is never the ceiling. Rotation is per call, not per session, so a
  chatty conversation cannot drain one free allowance on its own.
* An empty match is not a failure. A backend that answers with nothing is asked
  again elsewhere, because a peer may know pages its index does not carry. Only
  a real failure is reported, and it names every backend it tried so a rate
  limit can be told apart from a network fault.

Layout: `base.py` is the backend contract and the shapes backends share,
`transport.py` is the one HTTP call and the one place failures are classified,
`exa.py` / `parallel.py` / `keenable.py` are one backend each, and `stats.py`
records what happened. None of them is meant to be imported from outside; this
module is the seam.
"""

from __future__ import annotations

import itertools
import logging

import httpx

from nova.llm import ToolResult
from nova.settings import get_settings
from nova.tools.registry import tool
from nova.tools.web_search.base import (
    EMPTY_RESULT_MESSAGE,
    SearchBackend,
    SearchBackendError,
    render_results,
)
from nova.tools.web_search.exa import ExaBackend
from nova.tools.web_search.keenable import KeenableBackend
from nova.tools.web_search.parallel import ParallelBackend
from nova.tools.web_search.stats import (
    OUTCOME_EMPTY,
    OUTCOME_OK,
    record_usage,
    render,
    summarize,
    usage_path,
)
from nova.tools.web_search.transport import REQUEST_TIMEOUT_SECONDS, call_backend

LOGGER = logging.getLogger(__name__)

DEFAULT_LIMIT = 5
MAX_LIMIT = 10


def resolve_limit(requested: int) -> int:
    """Clamp a model-supplied result count into the supported range.

    Three layers guard this, in the order a bad value can arrive: the schema
    states the bounds, the runtime clamps anyway because a model is not a
    schema, and non-numeric input falls back to the default rather than raising
    a tool error over a recoverable argument.

    Args:
        requested: The count the model asked for.

    Returns:
        A count within ``[1, MAX_LIMIT]``, or the default when unusable.
    """
    try:
        value = int(requested)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return min(max(value, 1), MAX_LIMIT)


EXA = ExaBackend()
PARALLEL = ParallelBackend()
KEENABLE = KeenableBackend()

BACKENDS: dict[str, SearchBackend] = {
    EXA.name: EXA,
    PARALLEL.name: PARALLEL,
    KEENABLE.name: KEENABLE,
}

_rotation = itertools.count()


def candidates() -> list[SearchBackend]:
    """Return the backends to try, honouring a configured provider pin."""
    provider = get_settings().web_search.provider
    if provider in BACKENDS:
        return [BACKENDS[provider]]
    return list(BACKENDS.values())


def rotating_order() -> list[SearchBackend]:
    """Return the candidate backends starting at the next one in rotation.

    Rotating per call spreads usage evenly across the ring instead of pinning
    a single conversation to one backend, so a chatty session cannot exhaust
    one free allowance on its own.

    Returns:
        The backends to try, in the order they should be tried.
    """
    ring = candidates()
    if len(ring) == 1:
        return ring
    offset = next(_rotation) % len(ring)
    return ring[offset:] + ring[:offset]


@tool(
    name="web_search",
    description=(
        "Search the web and return ranked result metadata: title, URL, and a short "
        "description of each hit. This tool does NOT return page content, so pick "
        "the result worth reading and pass its URL to web_fetch. Backend-supported "
        "operators such as site:example.com, filetype:pdf, intitle:word, -term, or "
        '"exact phrase" may work.'
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "minimum": 1,
                "maximum": MAX_LIMIT,
                "default": DEFAULT_LIMIT,
            },
        },
        "required": ["query"],
    },
)
async def web_search(query: str, limit: int = DEFAULT_LIMIT) -> ToolResult:
    """Search the web, rotating across keyless public backends.

    Returns metadata only. Page content is a separate call so the context
    window pays for the pages that actually get read rather than for every
    candidate.

    Args:
        query: The search query.
        limit: Maximum results to return; clamped to the supported range.

    Returns:
        A successful result carrying ranked result metadata as JSON, a
        successful result reporting that nothing matched, or a failed result
        describing every backend that was tried.
    """
    count = resolve_limit(limit)
    failures: list[str] = []
    searched_any = False

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for backend in rotating_order():
            LOGGER.debug("web_search routing to %s", backend.name)
            try:
                outcome = await call_backend(client, backend, query, count)
            except SearchBackendError as exc:
                record_usage(backend.name, exc.kind)
                LOGGER.warning("web_search backend %s failed: %s", backend.name, exc)
                failures.append(str(exc))
                continue
            if outcome.hits:
                record_usage(backend.name, OUTCOME_OK, outcome.quota_remaining)
                return ToolResult(success=True, content=render_results(outcome.hits))
            # An empty match is not a failure: keep looking, since a peer may
            # know pages this backend's index does not carry.
            LOGGER.info("web_search backend %s matched nothing", backend.name)
            record_usage(backend.name, OUTCOME_EMPTY, outcome.quota_remaining)
            searched_any = True

    if failures:
        detail = "; ".join(failures)
        LOGGER.warning("web_search failed: %s", detail)
        return ToolResult(success=False, content=f"Search error: {detail}")
    if searched_any:
        return ToolResult(
            success=True,
            content=(
                f"{EMPTY_RESULT_MESSAGE}. Try a different query, a broader one, "
                "or drop site: or filetype: operators."
            ),
        )
    return ToolResult(
        success=False, content="Search error: no search backend available"
    )


def usage_report(days: int = 7) -> str:
    """Summarise recorded backend usage as a table.

    Args:
        days: How many days of history to include.

    Returns:
        A rendered table, or a hint when nothing has been recorded yet.
    """
    return render(summarize(days))


TOOL = web_search

__all__ = [
    "BACKENDS",
    "DEFAULT_LIMIT",
    "EXA",
    "KEENABLE",
    "MAX_LIMIT",
    "PARALLEL",
    "TOOL",
    "candidates",
    "resolve_limit",
    "rotating_order",
    "usage_path",
    "usage_report",
    "web_search",
]
