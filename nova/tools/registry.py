"""
Tool registry.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Callable, Optional, Any

_tool_metadata: dict = {}


def tool(
    name: str = None,
    description: str = "",
    parameters: dict = None,
):
    """Tool decorator."""
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        _tool_metadata[tool_name] = {
            "name": tool_name,
            "description": description or func.__doc__ or "",
            "parameters": parameters or {},
            "func": func,
        }
        return func
    return decorator


@dataclass
class Tool:
    """Tool definition."""
    name: str
    description: str
    func: Callable
    params_schema: dict = field(default_factory=dict)
    read_only: bool = True
    concurrent_safe: bool = True


class ToolRegistry:
    """Tool registry."""

    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(self, func: Callable, name: str = None) -> None:
        """Register a tool function using decorator metadata."""
        tool_name = name or func.__name__
        metadata = _tool_metadata.get(tool_name, {})
        t = Tool(
            name=metadata.get("name", tool_name),
            description=metadata.get("description", ""),
            func=func,
            params_schema=metadata.get("parameters", {}),
        )
        self.tools[t.name] = t

    def register_by_metadata(self, tool_name: str) -> bool:
        """Register a tool from global metadata."""
        metadata = _tool_metadata.get(tool_name)
        if not metadata:
            return False
        func = metadata.get("func")
        if not func:
            return False
        self.register(func, tool_name)
        return True

    def unregister(self, name: str):
        """Unregister a tool."""
        self.tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self.tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self.tools.values())

    def get_schema(self) -> list[dict]:
        """Return all tool schemas for LLM consumption."""
        schemas = []
        for tool in self.tools.values():
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": self._convert_schema(tool.params_schema),
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": self._convert_schema(tool.params_schema)
                }
            })
        return schemas

    def _convert_schema(self, schema: dict) -> dict:
        """Convert a schema into OpenAI function-calling format."""
        if not schema:
            return {"type": "object", "properties": {}}

        return {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", [])
        }

    async def call(self, name: str, **kwargs) -> dict:
        """Invoke a tool."""
        tool = self.get(name)
        if not tool:
            return {"success": False, "error": f"Tool {name} not found"}

        try:
            # Execute the tool function.
            if asyncio.iscoroutinefunction(tool.func):
                result = await tool.func(**kwargs)
            else:
                result = tool.func(**kwargs)

            # Normalize the result format.
            if isinstance(result, dict):
                if "success" not in result:
                    return {"success": True, "result": result}
                return result

            return {"success": True, "result": result}

        except Exception as e:
            return {"success": False, "error": str(e)}


# Global tool registry.
_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Get the global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
