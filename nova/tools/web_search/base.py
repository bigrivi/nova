"""The contracts a search backend implements, and the shapes they share.

Everything in here is backend-agnostic: what a backend is handed, what it must
return, and the one rendering routine that keeps every provider's payload
looking the same to the model. A backend file supplies its own endpoint, its own
credentials, and its own payload rules; nothing here knows any provider's name.

Search returns metadata only -- title, URL, a short description, and rank. It
never returns page content, because a page is worth reading only after someone
has decided it is, and paying for eight full pages to find that out costs the
context window more than the answer is worth. Reading is ``web_fetch``'s job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import regex

#: Shown when every backend answered but none matched. Not a failure: the
#: search ran, there was just nothing to report.
EMPTY_RESULT_MESSAGE = "No search results found"


class SearchBackendError(Exception):
    """A backend call failed in a way the caller may want to distinguish.

    Args:
        message: Human-readable description shown to the user.
        kind: Machine-readable category: ``rate_limited``, ``timeout``,
            ``transport``, ``http``, or ``payload``. Used for usage accounting
            so quota limits can be told apart from ordinary failures.
    """

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class SearchRequest:
    """A backend-specific HTTP request, built by the backend itself.

    Attributes:
        url: Absolute endpoint URL.
        headers: Complete header set, including any credential.
        body: JSON body.
    """

    url: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass(frozen=True)
class BackendResponse:
    """What one backend returned.

    Attributes:
        hits: Result rows, empty when nothing matched.
        quota_remaining: Calls left in the current window, when the backend
            reports it. Recorded so a shared free pool can be told apart from
            a per-client one.
    """

    hits: list[SearchHit]
    quota_remaining: int | None = None


@dataclass(frozen=True)
class SearchHit:
    """One search result, as metadata.

    Attributes:
        title: Page title, used to tell candidates apart.
        url: Absolute page URL, which ``web_fetch`` can read.
        description: A short summary of the page. Its length is the backend's
            choice: a provider that curates its own highlights can afford more
            than one that ships raw page text.
        published: Publication date when the backend reports one.
    """

    title: str
    url: str
    description: str = ""
    published: str = ""

    def to_json(self, position: int) -> dict[str, object]:
        """Render this hit as the dict the model receives.

        Key order is part of the contract: this object reaches the model as
        JSON, and the leading keys are what get read first. Title leads because
        it is the strongest discriminator between candidates.

        Args:
            position: 1-based rank of this hit.

        Returns:
            The hit as a plain dict.
        """
        return {
            "position": position,
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "published": self.published,
        }


def render_results(hits: list[SearchHit]) -> str:
    """Render result rows as the JSON payload the model receives.

    Args:
        hits: The rows to render, already limited and in rank order.

    Returns:
        A JSON document with a single ``results`` array.
    """
    payload = {
        "results": [hit.to_json(index) for index, hit in enumerate(hits, start=1)]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


class SearchBackend:
    """One search endpoint and its request/response dialect.

    A backend owns its endpoint, its credentials, and how it shapes a query and
    renders a reply. This class holds only what every dialect shares; the wire
    protocol lives one level down, in :class:`McpBackend` or :class:`RestBackend`.

    The split matters because a method that only one protocol has is not part of
    this contract. A REST backend has no MCP tool name, and an MCP backend has no
    plain HTTP body to post -- declaring either here would leave every subclass
    carrying methods it can only raise from.
    """

    #: Short name used for routing, log lines, and usage records.
    name = ""
    #: Endpoint this backend posts to.
    url = ""
    #: Characters of description to keep per result. Backends differ because
    #: their payloads differ: a provider that curates its own highlights can
    #: afford more than one that ships raw page text.
    #:
    #: Intentionally has no default. Every backend must state its own budget,
    #: because the only sensible fallback -- keep everything -- is the one that
    #: defeats metadata-only search. Reading the attribute is how usage
    #: accounting sizes the field, so a backend that left it unset would report
    #: a budget it was not applying.
    description_limit: int

    def api_key(self) -> str:
        """Return this backend's optional key, empty when running keyless."""
        raise NotImplementedError

    def describe_error(self, response: httpx.Response) -> str | None:
        """Explain a failed request from the body, when the body explains it.

        A backend that answers a rejection with a structured body -- an error
        code and a message naming what was wrong -- can say far more than a
        status line can. The transport calls this instead of parsing the
        failure, so without an override the reason is lost even though the
        backend received it.

        Args:
            response: The failed HTTP response, status already known to be 4xx
                or 5xx.

        Returns:
            The reason as a short phrase, or None to let the transport report
            the status on its own. Never raises: this runs while another
            failure is already being reported.
        """
        return None

    def request(self, query: str, num_results: int) -> SearchRequest:
        """Build the request to send.

        Args:
            query: The search query.
            num_results: Requested result count.

        Returns:
            The request, carrying a credential only when one is configured.
        """
        raise NotImplementedError

    def parse(self, response: httpx.Response, limit: int) -> list[SearchHit]:
        """Decode a successful response into result rows.

        Search deliberately does not return page content. A result row carries
        only what the model needs to decide whether a page is worth fetching:
        a title, a URL, a short description, and the ranking position that lets
        an answer cite "the third result". Page content is ``web_fetch``'s job.

        Args:
            response: The HTTP response.
            limit: Maximum rows to return.

        Returns:
            The result rows, possibly empty when nothing matched.
        """
        raise NotImplementedError


class RestBackend(SearchBackend):
    """A backend reached by posting JSON and reading JSON back.

    There is no envelope to unwrap, so :meth:`parse` decodes the body directly.
    A subclass supplies its own body, headers, and row rendering. How a
    credential is attached is left to :meth:`request` rather than declared here,
    because a REST backend may authenticate by header, by query parameter, or
    not at all.
    """

    def parse(self, response: httpx.Response, limit: int) -> list[SearchHit]:
        """Decode a JSON body into result rows.

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
        """Build result rows from an already-decoded body.

        Args:
            payload: Decoded response body.
            limit: Maximum rows to return.

        Returns:
            The result rows.
        """
        raise NotImplementedError


class McpBackend(SearchBackend):
    """A backend reached through a hosted MCP server.

    Supplies everything the JSON-RPC ``tools/call`` exchange needs, so a subclass
    only states its endpoint, its tool name, its arguments, and how to read the
    payload it answers with.
    """

    #: Remote MCP tool name.
    tool_name = ""

    def auth_headers(self, key: str) -> dict[str, str]:
        """Return headers that authenticate *key* against this backend.

        Args:
            key: The backend's API key.

        Returns:
            Headers carrying the credential.
        """
        raise NotImplementedError

    def request_arguments(self, query: str, num_results: int) -> dict[str, Any]:
        """Build the ``tools/call`` arguments for this backend.

        Args:
            query: The search query.
            num_results: Requested result count.

        Returns:
            Arguments for the named tool.
        """
        raise NotImplementedError

    def rows(self, text: str, limit: int) -> list[SearchHit]:
        """Parse the payload text out of a reply into result rows.

        Args:
            text: The payload text extracted from the response envelope.
            limit: Maximum rows to return; the backend decides whether it can
                honour this or only to be sliced afterwards.

        Returns:
            The result rows, possibly empty when nothing matched.
        """
        raise NotImplementedError

    def request(self, query: str, num_results: int) -> SearchRequest:
        """Build the JSON-RPC request for the hosted MCP server.

        Args:
            query: The search query.
            num_results: Requested result count.

        Returns:
            The request to send, carrying a credential only when one is
            configured.
        """
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        key = self.api_key()
        if key:
            headers.update(self.auth_headers(key))
        arguments = self.request_arguments(query, num_results)
        return SearchRequest(self.url, headers, mcp_body(self.tool_name, arguments))

    def parse(self, response: httpx.Response, limit: int) -> list[SearchHit]:
        """Unwrap a hosted MCP response into result rows.

        Args:
            response: The HTTP response.
            limit: Maximum rows to return.

        Returns:
            The result rows.

        Raises:
            SearchBackendError: If the envelope carries no usable payload.
        """
        text = extract_mcp_text(response.text)
        if not text:
            raise SearchBackendError(
                f"{self.name} returned no parsable result payload", "payload"
            )
        return self.rows(text, limit)


def mcp_body(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Wrap tool arguments in a JSON-RPC ``tools/call`` envelope.

    Args:
        tool: Remote tool name.
        arguments: Tool arguments.

    Returns:
        The JSON-RPC request body.
    """
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


def extract_mcp_text(payload: str) -> str:
    """Pull the tool's text payload out of an MCP response body.

    Backends disagree on framing: one answers with an SSE stream while another
    answers with a plain JSON document, so the whole body is tried first and
    SSE ``data:`` lines are the fallback.

    Args:
        payload: Raw response body.

    Returns:
        The tool's text payload, or an empty string when absent.
    """
    trimmed = payload.strip()
    candidates = [trimmed] if trimmed.startswith("{") else []
    candidates += [
        line[6:] for line in payload.splitlines() if line.startswith("data: ")
    ]

    for candidate in candidates:
        try:
            document = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(document, dict):
            continue
        result = document.get("result")
        if not isinstance(result, dict):
            continue
        content = result.get("content")
        if not isinstance(content, list) or not content:
            continue
        first = content[0]
        if isinstance(first, dict) and first.get("text"):
            return str(first["text"])
    return ""


#: Splits text into user-perceived characters. An emoji built from several code
#: points -- a ZWJ family, a skin tone, a flag -- is one cluster, so cutting on
#: these boundaries leaves no half-drawn glyph behind.
_GRAPHEME = regex.compile(r"\X")

#: How much of a broken-off final word is tolerated before the cut retreats to
#: the space before it. Roughly a short word, so the budget is not spent
#: recovering from a cut that landed inside a long word anyway.
_MAX_TRAILING_FRAGMENT = 12

#: Appended when a description was cut, so the model can tell a truncated
#: summary from a complete one instead of reading a clipped sentence as the
#: provider's full opinion.
TRUNCATION_MARK = "…"


def coerce_description(value: Any, limit: int) -> str:
    """Normalise a backend's description field into bounded plain text.

    Providers disagree on shape: some ship a curated string, some a list of
    passages, some raw page text. Whitespace is collapsed because page dumps
    arrive with the layout still in them, and the result is capped because the
    whole point of metadata-only search is that it stays cheap -- the budget
    belongs to the caller, so a provider that sends megabytes of excerpt cannot
    spend the context window.

    Cutting happens on a grapheme-cluster boundary rather than a code point.
    A code point can be a lone half of what a reader sees as one character: a
    family emoji, a skin-toned thumb, a flag, an accented letter. Slicing
    between those leaves a broken glyph at the end of the description, which
    the model then reads as part of the text. Where the cluster boundary falls
    near a word boundary the cut moves back to the space, so the summary does
    not end mid-word; CJK text has no such spaces and is cut at the cluster.

    Args:
        value: The raw field, which may be a string, a list of strings, or None.
        limit: Maximum characters to keep, including the truncation mark. A
            non-positive value keeps all of it, which is why every backend has
            to declare a positive budget rather than relying on a default.

    Returns:
        Bounded single-line text, empty when there is nothing usable. Cut text
        ends in :data:`TRUNCATION_MARK`.
    """
    if isinstance(value, list):
        parts = [str(part).strip() for part in value if str(part).strip()]
        text = " ".join(parts)
    elif value is None:
        text = ""
    else:
        text = str(value)
    text = " ".join(text.split())
    if limit <= 0:
        return text
    return _truncate(text, limit).strip()


def _truncate(text: str, limit: int) -> str:
    """Cut *text* to *limit* characters without breaking a grapheme cluster.

    Args:
        text: Single-line text, already whitespace-collapsed.
        limit: Maximum characters including the truncation mark.

    Returns:
        The text, cut at a cluster boundary and marked when anything was
        dropped. The mark costs one of the budget's characters, so a result is
        never longer than *limit*.
    """
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATION_MARK):
        # Too small to keep any text and still say it was cut. Dropping the
        # mark here would report a fragment as if it were whole, so the budget
        # is honoured instead and the caller sees a bare prefix.
        return text[:limit]
    # Leave room for the mark: it is information about the cut, so a summary
    # that used the whole budget silently would misrepresent what was dropped.
    budget = limit - len(TRUNCATION_MARK)
    clusters = _GRAPHEME.findall(text[: budget + 1])
    kept = "".join(clusters)
    if len(kept) > budget:
        # The cluster straddles the boundary; drop it rather than split it.
        kept = "".join(clusters[:-1])
    return _retreat_to_word_boundary(kept) + TRUNCATION_MARK


def _retreat_to_word_boundary(text: str) -> str:
    """Move a cut back to the last space, when one is close enough to matter.

    Only Latin-script spacing counts as a word boundary: CJK text is written
    without spaces, so there is nothing to retreat to and the cluster boundary
    already stands.

    Args:
        text: The cut text, which may end mid-word.

    Returns:
        The text ending at a space, or unchanged when no space appears in the
        final stretch.
    """
    head, sep, tail = text.rpartition(" ")
    if sep and len(tail) <= _MAX_TRAILING_FRAGMENT:
        return head
    return text


def hits_to_rows(
    backend: SearchBackend,
    hits: list[Any],
    limit: int,
    description_keys: tuple[str, ...],
) -> list[SearchHit]:
    """Turn raw hit objects into metadata rows.

    Shared by the backends that return structured hits rather than prose. A hit
    without a URL is skipped rather than raising: a malformed entry should cost
    one result, not the whole search.

    Args:
        backend: The calling backend, used for its name and description budget.
        hits: Raw hit objects from the response.
        limit: Maximum rows to return; a non-positive value keeps them all.
        description_keys: Candidate fields holding the hit's text, tried in
            order until one yields something.

    Returns:
        The rows, in the order the backend ranked them.
    """
    budget = backend.description_limit
    rows: list[SearchHit] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        url = str(hit.get("url") or "").strip()
        if not url:
            continue
        description = ""
        for key in description_keys:
            description = coerce_description(hit.get(key), budget)
            if description:
                break
        rows.append(
            SearchHit(
                title=str(hit.get("title") or "").strip() or "(untitled)",
                url=url,
                description=description,
                published=published_label(hit),
            )
        )
        if 0 < limit <= len(rows):
            break
    return rows


def published_label(hit: dict[str, Any]) -> str:
    """Return a printable publication date for a hit, or an empty string.

    Args:
        hit: One result object.

    Returns:
        A ``YYYY-MM-DD`` date, or an empty string when the hit has none or
        carries an explicit ``N/A`` placeholder.
    """
    for key in ("publish_date", "published_at"):
        value = str(hit.get(key) or "").strip()
        if value and value != "N/A":
            return value[:10]
    return ""


def reject_non_object(backend_name: str, payload: Any) -> None:
    """Raise unless *payload* is a JSON object.

    Args:
        backend_name: Backend name, used for the error message.
        payload: Decoded response body.

    Raises:
        SearchBackendError: If the payload is not an object.
    """
    if not isinstance(payload, dict):
        raise SearchBackendError(
            f"{backend_name} returned a JSON {type(payload).__name__}, "
            "expected an object",
            "payload",
        )


def require_hit_list(backend_name: str, payload: dict[str, Any]) -> list[Any]:
    """Return the ``results`` list from a decoded payload.

    Args:
        backend_name: Backend name, used for the error message.
        payload: Decoded response body.

    Returns:
        The list of hits, possibly empty.

    Raises:
        SearchBackendError: If the payload carries no results list.
    """
    hits = payload.get("results")
    if not isinstance(hits, list):
        raise SearchBackendError(
            f"{backend_name} payload has no results list", "payload"
        )
    return hits
