from html.parser import HTMLParser

import httpx

from nova.llm import ToolResult
from nova.tools.registry import tool


MAX_RESPONSE_SIZE = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
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
        elif tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "iframe", "object", "embed"} and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6"}:
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
        if tag in {"script", "style", "noscript", "iframe", "object", "embed"} and self._skip_depth > 0:
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
async def web_fetch(url: str, format: str = "markdown", timeout: float = DEFAULT_TIMEOUT) -> ToolResult:
    if not url.startswith(("http://", "https://")):
        return ToolResult(success=False, content="URL must start with http:// or https://")

    timeout = min(max(float(timeout), 1.0), MAX_TIMEOUT)
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": _accept_header(format),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 403 and response.headers.get("cf-mitigated") == "challenge":
                response = await client.get(
                    url,
                    headers={**headers, "User-Agent": "opencode"},
                )
            response.raise_for_status()

            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                return ToolResult(success=False, content="Response too large (exceeds 5MB limit)")

            raw = response.content
            if len(raw) > MAX_RESPONSE_SIZE:
                return ToolResult(success=False, content="Response too large (exceeds 5MB limit)")

            content_type = response.headers.get("content-type", "")
            content = response.text
            rendered = _render_content(content, content_type, format)
            return ToolResult(success=True, content=rendered)
    except httpx.TimeoutException:
        return ToolResult(success=False, content="Request timed out")
    except httpx.HTTPError as e:
        return ToolResult(success=False, content=f"HTTP error: {e}")
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = web_fetch
