import hashlib
import logging
from html.parser import HTMLParser
from pathlib import Path

import httpx

from nova.llm import ToolResult
from nova.settings import get_settings
from nova.tools.registry import tool

LOGGER = logging.getLogger(__name__)

MAX_RESPONSE_SIZE = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0

#: Characters of a fetched page returned inline. Search hands over titles and
#: URLs only, so this is where a page's cost lands; the rest is written to disk.
DEFAULT_CHAR_LIMIT = 15000
MIN_CHAR_LIMIT = 2000
MAX_CHAR_LIMIT = 500_000

#: Ceiling on the copy written to disk, so one oversized page cannot write
#: unbounded bytes on every fetch. The model only ever sees ``char_limit``.
MAX_STORED_CHARS = 2_000_000
CACHE_DIRNAME = "web-cache"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "iframe", "object", "embed"}:
            self._skip_depth += 1
        elif tag in {
            "p",
            "div",
            "section",
            "article",
            "li",
            "br",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if (
            tag in {"script", "style", "noscript", "iframe", "object", "embed"}
            and self._skip_depth > 0
        ):
            self._skip_depth -= 1
        elif tag in {
            "p",
            "div",
            "section",
            "article",
            "li",
            "br",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self._parts).splitlines()]
        return "\n".join(line for line in lines if line).strip()


class _HTMLMarkdownExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []
        self._href_stack: list[str | None] = []
        self._heading_level: int | None = None
        self._heading_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "iframe", "object", "embed"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_level = int(tag[1])
            self._heading_buffer = []
            self._parts.append("\n")
        elif tag == "p":
            self._parts.append("\n")
        elif tag == "li":
            self._parts.append("\n- ")
        elif tag == "br":
            self._parts.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href")
            self._href_stack.append(href)

    def handle_endtag(self, tag: str) -> None:
        if (
            tag in {"script", "style", "noscript", "iframe", "object", "embed"}
            and self._skip_depth > 0
        ):
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if self._heading_level and tag == f"h{self._heading_level}":
            text = " ".join("".join(self._heading_buffer).split())
            if text:
                self._parts.append(f"{'#' * self._heading_level} {text}\n")
            self._heading_level = None
            self._heading_buffer = []
        elif tag == "p":
            self._parts.append("\n")
        elif tag == "a" and self._href_stack:
            self._href_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._heading_level is not None:
            self._heading_buffer.append(data)
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._href_stack and self._href_stack[-1]:
            self._parts.append(f"[{text}]({self._href_stack[-1]})")
        else:
            self._parts.append(text)

    def get_markdown(self) -> str:
        lines = [line.rstrip() for line in "".join(self._parts).splitlines()]
        filtered: list[str] = []
        previous_blank = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if not previous_blank and filtered:
                    filtered.append("")
                previous_blank = True
                continue
            filtered.append(stripped)
            previous_blank = False
        return "\n".join(filtered).strip()


def _accept_header(format: str) -> str:
    if format == "markdown":
        return "text/markdown;q=1.0, text/x-markdown;q=0.9, text/plain;q=0.8, text/html;q=0.7, */*;q=0.1"
    if format == "text":
        return "text/plain;q=1.0, text/markdown;q=0.9, text/html;q=0.8, */*;q=0.1"
    if format == "html":
        return "text/html;q=1.0, application/xhtml+xml;q=0.9, text/plain;q=0.8, text/markdown;q=0.7, */*;q=0.1"
    return "*/*"


def _extract_text_from_html(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.get_text()


def _convert_html_to_markdown(html: str) -> str:
    parser = _HTMLMarkdownExtractor()
    parser.feed(html)
    markdown = parser.get_markdown()
    return markdown or _extract_text_from_html(html)


def _render_content(content: str, content_type: str, format: str) -> str:
    if format == "html":
        return content
    if "text/html" in content_type:
        if format == "text":
            return _extract_text_from_html(content)
        return _convert_html_to_markdown(content)
    return content


@tool(
    name="web_fetch",
    description="Fetch content from a URL. Use to retrieve and analyze web pages, API responses, or documentation. Returns content in markdown format by default.",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
            "format": {
                "type": "string",
                "description": "Response format: 'text', 'markdown', or 'html'. Default: 'markdown'",
                "enum": ["text", "markdown", "html"],
                "default": "markdown",
            },
            "timeout": {
                "type": "number",
                "description": "Optional timeout in seconds (max 120). Default: 30",
            },
        },
        "required": ["url"],
    },
)
def _clamp_char_limit(value: object) -> int:
    """Clamp a model-supplied character budget into the supported range.

    Below the floor the truncation notice would dominate what little text is
    left; the ceiling exists so a mistyped budget cannot blow up the context.

    Args:
        value: The requested budget; anything unusable yields the default.

    Returns:
        A budget within ``[MIN_CHAR_LIMIT, MAX_CHAR_LIMIT]``.
    """
    try:
        requested = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return DEFAULT_CHAR_LIMIT
    return max(MIN_CHAR_LIMIT, min(requested, MAX_CHAR_LIMIT))


def _offload_path(url: str, content: str) -> Path:
    """Write a full page to the cache so a truncated fetch stays recoverable.

    Total by construction: caching is a convenience, and nothing about a cache
    problem may turn a page the model already fetched into a failed tool call.
    Every fallible step is inside the guard, including resolving the settings
    block, so the caller can treat an empty return as "no copy available".

    Args:
        url: The page that was fetched, used for the on-disk identity.
        content: The full page text.

    Returns:
        The path written, or an empty path when nothing could be written.
    """
    try:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        directory = get_settings().home / CACHE_DIRNAME
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest}.md"
        stored = content[:MAX_STORED_CHARS]
        if len(content) > MAX_STORED_CHARS:
            stored += f"\n\n[stored copy truncated at {MAX_STORED_CHARS:,} chars]"
        path.write_text(stored, encoding="utf-8")
    except Exception as exc:
        # Deliberately broad: caching must never fail the call.
        LOGGER.warning("could not store full page for %s: %s", url, exc)
        return Path()
    return path


def _budget_content(content: str, url: str, budget: int) -> tuple[str, bool]:
    """Trim a page to the caller's budget, keeping its head and tail.

    Head and tail rather than the head alone because the parts of a page that
    decide what it is -- the title and the conclusion -- sit at opposite ends,
    and a model that loses either one usually loses the ability to tell
    whether it fetched the right page.

    Args:
        content: The rendered page text.
        url: The source URL, whose hash names the offloaded copy.
        budget: Characters to return; the budget itself, never the full page.

    Returns:
        Tuple of the text to return and whether anything was omitted.
    """
    if len(content) <= budget:
        return content, False

    head_budget = int(budget * 0.75)
    tail_budget = budget - head_budget
    head = content[:head_budget]
    tail = content[-tail_budget:]
    omitted = len(content) - head_budget - tail_budget
    path = _offload_path(url, content)
    pointer = f" Read it with the read tool: {path}" if path else ""
    notice = f"\n\n[... {omitted:,} chars omitted ...]{pointer}\n\n"
    return f"{head}{notice}{tail}", True


@tool(
    name="web_fetch",
    description=(
        "Fetch one URL and return its content as markdown. This is how you read a "
        "page found by web_search, which returns titles and URLs but no content. "
        "Long pages are trimmed to a character budget and the full text is saved "
        "to disk; the note in the output gives the path to read the rest."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
            "format": {
                "type": "string",
                "description": "Response format: 'text', 'markdown', or 'html'. Default: 'markdown'",
                "enum": ["text", "markdown", "html"],
                "default": "markdown",
            },
            "char_limit": {
                "type": "integer",
                "description": (
                    "Character budget for the returned page. Larger pages keep "
                    "their head and tail; the full text is saved to disk."
                ),
                "minimum": MIN_CHAR_LIMIT,
                "maximum": MAX_CHAR_LIMIT,
            },
            "timeout": {
                "type": "number",
                "description": "Optional timeout in seconds (max 120). Default: 30",
            },
        },
        "required": ["url"],
    },
)
async def web_fetch(
    url: str,
    format: str = "markdown",
    char_limit: int = DEFAULT_CHAR_LIMIT,
    timeout: float = DEFAULT_TIMEOUT,
) -> ToolResult:
    """Fetch one URL and return its content within a character budget.

    Args:
        url: The page to fetch; must be http or https.
        format: Response format, one of ``text``, ``markdown`` or ``html``.
        char_limit: Character budget, clamped to the supported range.
        timeout: Request timeout in seconds, capped at ``MAX_TIMEOUT``.

    Returns:
        A successful result carrying the page, trimmed when it exceeds the
        budget, or a failed result describing the failure.
    """
    if not url.startswith(("http://", "https://")):
        return ToolResult(
            success=False, content="URL must start with http:// or https://"
        )

    budget = _clamp_char_limit(char_limit)
    timeout = min(max(float(timeout), 1.0), MAX_TIMEOUT)
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": _accept_header(format),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            if (
                response.status_code == 403
                and response.headers.get("cf-mitigated") == "challenge"
            ):
                response = await client.get(
                    url,
                    headers={**headers, "User-Agent": "nova"},
                )
            response.raise_for_status()

            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                return ToolResult(
                    success=False, content="Response too large (exceeds 5MB limit)"
                )

            raw = response.content
            if len(raw) > MAX_RESPONSE_SIZE:
                return ToolResult(
                    success=False, content="Response too large (exceeds 5MB limit)"
                )

            content_type = response.headers.get("content-type", "")
            content = response.text
            rendered = _render_content(content, content_type, format)
            rendered, trimmed = _budget_content(rendered, url, budget)
            LOGGER.info(
                "web_fetch %s: %d chars%s",
                url,
                len(rendered),
                " (trimmed)" if trimmed else "",
            )
            return ToolResult(success=True, content=rendered)
    except httpx.TimeoutException:
        return ToolResult(success=False, content="Request timed out")
    except httpx.HTTPError as e:
        return ToolResult(success=False, content=f"HTTP error: {e}")
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = web_fetch
