"""CompanyLens MCP server.

Exposes all 9 CompanyLens tools over the Model Context Protocol so any
MCP client (Claude Desktop, Cursor, etc.) can call them.

Run with::

    python -m companylens.mcp_server.server          # stdio (default)
    python -m companylens.mcp_server.server --http   # streamable-http

Or via Make::

    make mcp
"""

from __future__ import annotations

import sys
from typing import Any

from mcp.server.mcpserver import MCPServer  # mcp >= 2.0

from companylens.clients.companies_house import CompaniesHouseClient
from companylens.clients.fca import FCAClient
from companylens.clients.news import NewsClient
from companylens.config import get_settings
from companylens.models import ToolResult

print("CompanyLens MCP server starting...", file=sys.stderr)

mcp = MCPServer("CompanyLens")

_settings = get_settings()

# Client singletons — created once at module import time.
_ch = CompaniesHouseClient()
_fca = FCAClient()
_news = NewsClient()


def _dump(result: ToolResult) -> dict[str, Any]:
    """Serialise a ToolResult to a JSON-safe dict."""
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Companies House tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_companies(query: str, limit: int = 5) -> dict[str, Any]:
    """Search the Companies House register by company name or number.

    Returns a ranked list of matching UK companies with their number, status,
    incorporation date, and address locality.  Use this first when you only
    have a name and need to find the exact company number.

    Args:
        query: Company name or number to search for.
        limit: Maximum number of results to return (1-20).
    """
    result = await _ch.search_companies(query=query, limit=limit)
    return _dump(result)


@mcp.tool()
async def get_company_profile(company_number: str) -> dict[str, Any]:
    """Fetch the full Companies House profile for a single company.

    Returns status, type, incorporation date, SIC codes, whether accounts
    or the confirmation statement are overdue, insolvency/charges flags,
    and registered office locality.

    Args:
        company_number: 8-character Companies House number, e.g. '00445790'.
    """
    result = await _ch.get_company_profile(company_number=company_number)
    return _dump(result)


@mcp.tool()
async def get_officers(company_number: str) -> dict[str, Any]:
    """Return officer counts: active directors, secretaries, and recent resignations.

    A high resignation rate can indicate governance problems.
    No personal data (names, DOBs, addresses) is returned.

    Args:
        company_number: 8-character Companies House number.
    """
    result = await _ch.get_officers(company_number=company_number)
    return _dump(result)


@mcp.tool()
async def get_filing_history(company_number: str, limit: int = 20) -> dict[str, Any]:
    """Return the most recent Companies House filings for a company.

    Each filing includes date, type code, description, and category.
    Look for missing accounts, late confirmation statements, or unusual
    filings (voluntary strike-off, restoration) as risk signals.

    Args:
        company_number: 8-character Companies House number.
        limit: Maximum number of recent filings to return (1-50).
    """
    result = await _ch.get_filing_history(company_number=company_number, limit=limit)
    return _dump(result)


@mcp.tool()
async def get_psc(company_number: str) -> dict[str, Any]:
    """Return the Persons with Significant Control (PSC) register.

    Returns total count, breakdown by kind, names of corporate PSCs,
    and count of ceased PSCs.  Missing PSC data or complex offshore
    holding structures are risk indicators.

    Args:
        company_number: 8-character Companies House number.
    """
    result = await _ch.get_psc(company_number=company_number)
    return _dump(result)


@mcp.tool()
async def get_charges(company_number: str) -> dict[str, Any]:
    """Return registered charges (mortgages, debentures) for a company.

    Returns total count, outstanding vs satisfied, and date of the most
    recent charge.  Outstanding charges indicate secured creditors.

    Args:
        company_number: 8-character Companies House number.
    """
    result = await _ch.get_charges(company_number=company_number)
    return _dump(result)


@mcp.tool()
async def get_insolvency(company_number: str) -> dict[str, Any]:
    """Return insolvency history for a company.

    Returns a list of insolvency cases with type and key dates.
    An empty list means no insolvency history.  Any case is a significant
    risk signal.

    Args:
        company_number: 8-character Companies House number.
    """
    result = await _ch.get_insolvency(company_number=company_number)
    return _dump(result)


# ---------------------------------------------------------------------------
# FCA tool
# ---------------------------------------------------------------------------


@mcp.tool()
async def check_fca_register(company_name: str, company_number: str) -> dict[str, Any]:
    """Check whether a company is authorised on the FCA Financial Services Register.

    Returns found/not-found, FCA reference number (FRN), authorisation status,
    and match confidence.  A financial-services company not on the FCA register
    is a serious red flag.

    Args:
        company_name: Full company name as it appears on Companies House.
        company_number: 8-character Companies House number.
    """
    result = await _fca.check_fca_register(company_name=company_name, company_number=company_number)
    return _dump(result)


# ---------------------------------------------------------------------------
# News tool
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_news(company_name: str, days: int = 180, limit: int = 5) -> dict[str, Any]:
    """Search GDELT for recent news articles mentioning a company.

    Returns article title, URL, publication date, and domain.  Useful for
    detecting adverse media: fraud, scandal, sanctions, regulatory action,
    or financial distress.

    Args:
        company_name: Company name to search news for.
        days: Look-back window in days (1-365).
        limit: Maximum number of articles to return (1-20).
    """
    result = await _news.search_news(company_name=company_name, days=days, limit=limit)
    return _dump(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
