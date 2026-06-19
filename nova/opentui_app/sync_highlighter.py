"""Synchronous tree-sitter highlighter for opentui's sync event loop."""

from opentui.components._syntax_highlight import TreeSitterClient
from opentui.tree_sitter_client import PyTreeSitterClient


class SyncPyTreeSitterClient(TreeSitterClient):
    """Synchronous wrapper around PyTreeSitterClient.

    Calls _parse_sync directly instead of going through asyncio.to_thread,
    making it compatible with opentui's synchronous event loop.
    """

    def __init__(self):
        self._inner = PyTreeSitterClient()

    async def highlight_once(self, content: str, filetype: str) -> dict:
        ready = self._inner._ensure_ready(filetype)
        if not ready:
            return {"highlights": []}
        parser, query = ready
        highlights = self._inner._parse_sync(parser, query, content)
        return {"highlights": highlights}

    def supported_filetypes(self) -> list[str]:
        return self._inner.supported_filetypes

    def is_filetype_available(self, filetype: str) -> bool:
        return self._inner.is_filetype_available(filetype)


__all__ = ["SyncPyTreeSitterClient"]
