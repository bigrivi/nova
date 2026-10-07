"""Exa: a hosted MCP server whose payload is pre-rendered markdown.

Exa is the awkward one in the ring. Its REST API would return structured
highlights, but the REST API has no keyless tier -- it answers an unauthenticated
request with HTTP 402 -- and Nova's premise is that search must work without a
credential. So Exa goes through the hosted MCP server like the others, and that
server only offers markdown.

That means the metadata has to be recovered from prose. The format is a fixed
template, one block per result::

    Title: ...
    URL: ...
    Published: ...
    Author: ...
    Highlights:
    <body>

so the parser below reads the labelled fields and treats everything after
``Highlights:`` as the description. It is deliberately forgiving: a block
missing a URL is dropped rather than raising, because a malformed block should
cost one result, not the whole search.

A configured key is sent as an ``x-api-key`` header, which is the form Exa's
own documentation lists for the MCP endpoint; putting it in the URL instead
would leak it into access logs.
"""

from __future__ import annotations

from typing import Any

from nova.settings import get_settings
from nova.tools.web_search.base import SearchBackend, SearchHit, coerce_description

#: Exa's ``Highlights`` are passages the provider picked itself, so more of
#: them stay on-topic than a raw page dump would.
DESCRIPTION_LIMIT = 400

_FIELD_LABELS = ("Title:", "URL:", "Published:", "Author:", "Highlights:")


class ExaBackend(SearchBackend):
    """Exa's hosted MCP server; markdown payload, parsed back into rows."""

    name = "exa"
    url = "https://mcp.exa.ai/mcp"
    tool_name = "web_search_exa"

    def api_key(self) -> str:
        """Return the configured Exa key, empty when running keyless."""
        return get_settings().web_search.exa_api_key

    def auth_headers(self, key: str) -> dict[str, str]:
        """Authenticate via the ``x-api-key`` header.

        Args:
            key: Exa API key.

        Returns:
            Headers carrying the credential.
        """
        return {"x-api-key": key}

    def request_arguments(self, query: str, num_results: int) -> dict[str, Any]:
        """Build Exa's search arguments.

        Args:
            query: The search query.
            num_results: Requested result count; Exa honours this.

        Returns:
            Arguments for the ``web_search_exa`` tool.
        """
        return {
            "query": query,
            "numResults": num_results,
            "type": "auto",
            "livecrawl": "fallback",
        }

    def rows(self, text: str, limit: int) -> list[SearchHit]:
        """Recover result metadata from Exa's markdown.

        Args:
            text: Exa's markdown payload.
            limit: Maximum rows to return.

        Returns:
            One row per result block that carried a URL.
        """
        return parse_markdown_hits(text, limit)


def parse_markdown_hits(text: str, limit: int) -> list[SearchHit]:
    """Parse Exa's result markdown into metadata rows.

    Args:
        text: Exa's markdown payload, one result per block.
        limit: Maximum rows to return; a non-positive value keeps them all.

    Returns:
        The rows recovered from the markdown, in the order Exa ranked them.
    """
    hits: list[SearchHit] = []
    for block in text.split("\n\n"):
        fields: dict[str, str] = {}
        body: list[str] = []
        in_body = False
        for line in block.splitlines():
            if in_body:
                body.append(line)
                continue
            if line.strip() == "Highlights:":
                in_body = True
                continue
            label = next(
                (name for name in _FIELD_LABELS if line.startswith(name)), None
            )
            if label:
                fields[label.rstrip(":")] = line[len(label) :].strip()
        url = fields.get("URL", "")
        if not url:
            continue
        hits.append(
            SearchHit(
                title=fields.get("Title") or "(untitled)",
                url=url,
                description=coerce_description("\n".join(body), DESCRIPTION_LIMIT),
                # Exa writes "N/A" when it has no date; drop it rather than
                # handing the model a placeholder it might quote back.
                published=_clean_date(fields.get("Published", "")),
            )
        )
        if 0 < limit <= len(hits):
            break
    return hits


def _clean_date(value: str) -> str:
    """Return a publication date, or an empty string when there is none."""
    value = (value or "").strip()
    if not value or value.upper() == "N/A":
        return ""
    return value[:10]
