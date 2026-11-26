"""Tool registry: maps tool names to JSON schemas and callable async functions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from companylens.models import ToolResult


@dataclass
class ToolDefinition:
    """Metadata and implementation for a single agent tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object
    fn: Callable[..., Awaitable[ToolResult]]


class ToolRegistry:
    """Registry that maps tool names to their definitions.

    Usage::

        registry = ToolRegistry()
        registry.register(ToolDefinition(name="my_tool", ...))
        defn = registry.get("my_tool")
        result = await defn.fn(arg1=value1)
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, defn: ToolDefinition) -> None:
        """Add a tool definition to the registry."""
        self._tools[defn.name] = defn

    def get(self, name: str) -> ToolDefinition:
        """Return the ToolDefinition for *name*.

        Raises:
            KeyError: if no tool with that name has been registered.
        """
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"No tool registered with name '{name}'") from None

    def all_tools(self) -> list[ToolDefinition]:
        """Return all registered tool definitions in registration order."""
        return list(self._tools.values())

    def to_openai_format(self) -> list[dict[str, Any]]:
        """Return tool definitions in the OpenAI function-calling format.

        Each entry is::

            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": { ... }   # JSON Schema
                }
            }
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": defn.name,
                    "description": defn.description,
                    "parameters": defn.parameters,
                },
            }
            for defn in self._tools.values()
        ]
