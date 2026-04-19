import json

import httpx

from nova.llm import ToolResult
from nova.tools.registry import tool


API_BASE_URL = "https://mcp.exa.ai"
API_SEARCH_ENDPOINT = "/mcp"
DEFAULT_NUM_RESULTS = 8


def _build_search_request(query: str, num_results: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "web_search_exa",
            "arguments": {
                "query": query,
                "type": "auto",
                "numResults": num_results or DEFAULT_NUM_RESULTS,
                "livecrawl": "fallback",
            },
        },
    }


def _parse_sse_search_text(payload: str) -> str:
    for line in payload.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        content = data.get("result", {}).get("content", [])
        if content and isinstance(content[0], dict):
            text = content[0].get("text", "")
            if text:
                return text
    return ""


@tool(
    name="web_search",
    description="Search the web for information. Use for current events, recent data, or topics beyond your knowledge cutoff. Returns relevant web content.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 8)",
                "default": 8,
            },
        },
        "required": ["query"],
    },
)
async def web_search(query: str, num_results: int = 8) -> ToolResult:
    request_body = _build_search_request(query=query, num_results=num_results)
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{API_BASE_URL}{API_SEARCH_ENDPOINT}",
                headers=headers,
                json=request_body,
            )
            response.raise_for_status()
            response_text = response.text

        content = _parse_sse_search_text(response_text)
        if content:
            return ToolResult(success=True, content=content)
        return ToolResult(success=True, content="No search results found")
    except httpx.TimeoutException:
        return ToolResult(success=False, content="Search error: request timed out")
    except Exception as e:
        return ToolResult(success=False, content=f"Search error: {e}")


TOOL = web_search
