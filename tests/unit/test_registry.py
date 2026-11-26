"""Unit tests for the tool registry and build_registry."""

from __future__ import annotations

from datetime import UTC

from companylens.config import Settings
from companylens.tools.company_tools import build_registry
from companylens.tools.registry import ToolDefinition, ToolRegistry

# ---------------------------------------------------------------------------
# Expected tool names
# ---------------------------------------------------------------------------

EXPECTED_TOOL_NAMES = [
    "search_companies",
    "get_company_profile",
    "get_officers",
    "get_filing_history",
    "get_psc",
    "get_charges",
    "get_insolvency",
    "check_fca_register",
    "search_news",
]


# ---------------------------------------------------------------------------
# ToolRegistry unit tests
# ---------------------------------------------------------------------------


def test_registry_register_and_get() -> None:
    """register() stores a definition; get() retrieves it by name."""
    from datetime import datetime

    from companylens.models import ToolResult

    async def _dummy() -> ToolResult:
        return ToolResult(
            tool="dummy",
            args={},
            ok=True,
            source_url="https://example.com",
            retrieved_at=datetime.now(UTC),
        )

    registry = ToolRegistry()
    defn = ToolDefinition(
        name="dummy",
        description="A dummy tool.",
        parameters={"type": "object", "properties": {}},
        fn=_dummy,
    )
    registry.register(defn)
    retrieved = registry.get("dummy")
    assert retrieved.name == "dummy"
    assert retrieved.description == "A dummy tool."


def test_registry_get_missing_raises() -> None:
    """get() raises KeyError for an unregistered tool."""
    import pytest

    registry = ToolRegistry()
    with pytest.raises(KeyError, match="no_such_tool"):
        registry.get("no_such_tool")


def test_registry_all_tools_order() -> None:
    """all_tools() returns definitions in registration order."""
    from datetime import datetime

    from companylens.models import ToolResult

    async def _noop() -> ToolResult:  # pragma: no cover
        return ToolResult(
            tool="noop",
            args={},
            ok=True,
            source_url="https://example.com",
            retrieved_at=datetime.now(UTC),
        )

    registry = ToolRegistry()
    for name in ["alpha", "beta", "gamma"]:
        registry.register(
            ToolDefinition(
                name=name,
                description=f"Tool {name}",
                parameters={"type": "object", "properties": {}},
                fn=_noop,
            )
        )

    names = [d.name for d in registry.all_tools()]
    assert names == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# to_openai_format tests
# ---------------------------------------------------------------------------


def test_to_openai_format_shape() -> None:
    """to_openai_format() entries have the correct OpenAI function-calling shape."""
    from datetime import datetime

    from companylens.models import ToolResult

    async def _noop() -> ToolResult:  # pragma: no cover
        return ToolResult(
            tool="noop",
            args={},
            ok=True,
            source_url="https://example.com",
            retrieved_at=datetime.now(UTC),
        )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="my_tool",
            description="Does something.",
            parameters={
                "type": "object",
                "properties": {"foo": {"type": "string"}},
                "required": ["foo"],
            },
            fn=_noop,
        )
    )

    tools = registry.to_openai_format()
    assert len(tools) == 1
    entry = tools[0]
    assert entry["type"] == "function"
    func = entry["function"]
    assert isinstance(func, dict)
    assert func["name"] == "my_tool"
    assert func["description"] == "Does something."
    assert isinstance(func["parameters"], dict)


# ---------------------------------------------------------------------------
# build_registry integration tests
# ---------------------------------------------------------------------------


def test_build_registry_returns_9_tools() -> None:
    """build_registry returns a ToolRegistry with exactly 9 tools."""
    settings = Settings()
    registry = build_registry(settings)
    assert len(registry.all_tools()) == 9


def test_build_registry_tool_names() -> None:
    """build_registry registers all expected tool names."""
    settings = Settings()
    registry = build_registry(settings)
    names = {defn.name for defn in registry.all_tools()}
    assert names == set(EXPECTED_TOOL_NAMES)


def test_build_registry_openai_format_count() -> None:
    """to_openai_format returns one entry per tool."""
    settings = Settings()
    registry = build_registry(settings)
    tools = registry.to_openai_format()
    assert len(tools) == 9


def test_build_registry_openai_format_entries() -> None:
    """Every entry in to_openai_format has the correct top-level structure."""
    settings = Settings()
    registry = build_registry(settings)
    for entry in registry.to_openai_format():
        assert entry["type"] == "function"
        func = entry["function"]
        assert isinstance(func, dict)
        assert isinstance(func["name"], str) and func["name"]
        assert isinstance(func["description"], str) and func["description"]
        assert isinstance(func["parameters"], dict)


def test_build_registry_json_schemas_valid() -> None:
    """Every tool's JSON schema has type=object and a properties dict."""
    settings = Settings()
    registry = build_registry(settings)
    for defn in registry.all_tools():
        params = defn.parameters
        assert params.get("type") == "object", f"Tool '{defn.name}' schema missing type=object"
        assert isinstance(params.get("properties"), dict), (
            f"Tool '{defn.name}' schema missing properties dict"
        )


def test_build_registry_all_tools_callable() -> None:
    """Every registered tool has a callable fn attribute."""
    settings = Settings()
    registry = build_registry(settings)
    for defn in registry.all_tools():
        assert callable(defn.fn), f"Tool '{defn.name}' fn is not callable"
