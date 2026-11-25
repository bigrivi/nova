"""Compatibility import for the tool registry now provided by novakit."""

from novakit.tools.registry import (
    Tool,
    ToolRegistry,
    _tool_metadata,
    get_registry,
    tool,
)

__all__ = ["Tool", "ToolRegistry", "_tool_metadata", "get_registry", "tool"]
