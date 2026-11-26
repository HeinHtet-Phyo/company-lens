"""Integration tests for the CompanyLens MCP server.

These tests start the MCP server as a subprocess (stdio transport) and
connect to it with the MCP Python client to verify that all tools are
exposed correctly.

The actual tool-call tests are skipped until HTTP fixtures are recorded.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Expected tool names — must match company_tools.py
# ---------------------------------------------------------------------------

EXPECTED_TOOL_NAMES = {
    "search_companies",
    "get_company_profile",
    "get_officers",
    "get_filing_history",
    "get_psc",
    "get_charges",
    "get_insolvency",
    "check_fca_register",
    "search_news",
}

# Path to the server module so we can start it as a subprocess
_SERVER_MODULE = "companylens.mcp_server.server"

# Project root (two levels up from this file)
_PROJECT_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _python() -> str:
    """Return the Python interpreter path (prefer the venv one)."""
    venv_python = _PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_server_lists_all_tools() -> None:
    """Start the MCP server over stdio and assert all 9 tools are present."""
    pytest.importorskip("mcp")

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=_python(),
        args=["-m", _SERVER_MODULE],
        cwd=str(_PROJECT_ROOT),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool_names = {t.name for t in tools_result.tools}

    assert tool_names == EXPECTED_TOOL_NAMES, (
        f"Tool name mismatch.\n"
        f"  Expected: {sorted(EXPECTED_TOOL_NAMES)}\n"
        f"  Got:      {sorted(tool_names)}"
    )


@pytest.mark.asyncio
@pytest.mark.skip(
    reason=(
        "enable once HTTP fixtures are recorded — see tests/fixtures/README.md for instructions"
    )
)
async def test_mcp_search_companies_fixture() -> None:
    """Call search_companies with a known fixture response.

    To enable:
    1. Record a fixture for query='Tesco' using pytest-httpx or VCR.
    2. Update tests/fixtures/ with the recorded cassette.
    3. Remove the @pytest.mark.skip decorator.
    """
    pytest.importorskip("mcp")

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=_python(),
        args=["-m", _SERVER_MODULE],
        cwd=str(_PROJECT_ROOT),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_companies",
                arguments={"query": "Tesco", "limit": 3},
            )

    assert result is not None
    # The result content is a JSON-serialised ToolResult dict
    content = result.content
    assert len(content) > 0
