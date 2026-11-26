"""Register all CompanyLens tools in the tool registry.

Client classes are instantiated inside ``build_registry`` so this module
is importable without API keys present in the environment.
"""

from __future__ import annotations

from companylens.config import Settings
from companylens.models import ToolResult
from companylens.tools.registry import ToolDefinition, ToolRegistry

# ---------------------------------------------------------------------------
# JSON Schema helpers
# ---------------------------------------------------------------------------


def _obj(
    properties: dict[str, object],
    required: list[str] | None = None,
) -> dict[str, object]:
    """Shorthand for a JSON Schema object node."""
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required is not None:
        schema["required"] = required
    return schema


def _str(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _int(description: str, default: int | None = None) -> dict[str, object]:
    prop: dict[str, object] = {"type": "integer", "description": description}
    if default is not None:
        prop["default"] = default
    return prop


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_registry(settings: Settings) -> ToolRegistry:
    """Create all client instances and return a fully populated ToolRegistry.

    Args:
        settings: Application settings (API keys, etc.).

    Returns:
        A ToolRegistry with all 9 tools registered.
    """
    # Lazy imports so the module stays importable without API keys
    from companylens.clients.companies_house import CompaniesHouseClient
    from companylens.clients.fca import FCAClient
    from companylens.clients.news import NewsClient

    ch = CompaniesHouseClient()
    fca = FCAClient()
    news = NewsClient()

    registry = ToolRegistry()

    # ------------------------------------------------------------------
    # 1. search_companies
    # ------------------------------------------------------------------
    registry.register(
        ToolDefinition(
            name="search_companies",
            description=(
                "Search the Companies House register by company name or number. "
                "Returns a ranked list of matching UK companies with their number, "
                "status, incorporation date, and address locality. "
                "Use this first when you only have a name and need to find the "
                "exact company number before calling other tools."
            ),
            parameters=_obj(
                {
                    "query": _str("Company name or number to search for."),
                    "limit": _int("Maximum number of results to return (1-20).", default=5),
                },
                required=["query"],
            ),
            fn=lambda query, limit=5: ch.search_companies(query=query, limit=limit),
        )
    )

    # ------------------------------------------------------------------
    # 2. get_company_profile
    # ------------------------------------------------------------------
    registry.register(
        ToolDefinition(
            name="get_company_profile",
            description=(
                "Fetch the full Companies House profile for a single company "
                "by its 8-character company number. "
                "Returns company status (active/dissolved/etc.), type, "
                "incorporation date, SIC codes, whether accounts or the "
                "confirmation statement are overdue, whether there is an "
                "insolvency history or registered charges, and registered "
                "office locality. This is usually the first call after "
                "resolving the company number."
            ),
            parameters=_obj(
                {
                    "company_number": _str(
                        "8-character Companies House company number, e.g. '00445790'."
                    ),
                },
                required=["company_number"],
            ),
            fn=lambda company_number: ch.get_company_profile(company_number=company_number),
        )
    )

    # ------------------------------------------------------------------
    # 3. get_officers
    # ------------------------------------------------------------------
    registry.register(
        ToolDefinition(
            name="get_officers",
            description=(
                "Return officer counts for a company: number of active "
                "directors, active secretaries, and resignations in the last "
                "12 months. "
                "A high resignation rate can be a red flag for governance "
                "problems. No personal data (names, DOBs, addresses) is "
                "returned."
            ),
            parameters=_obj(
                {
                    "company_number": _str("8-character Companies House company number."),
                },
                required=["company_number"],
            ),
            fn=lambda company_number: ch.get_officers(company_number=company_number),
        )
    )

    # ------------------------------------------------------------------
    # 4. get_filing_history
    # ------------------------------------------------------------------
    registry.register(
        ToolDefinition(
            name="get_filing_history",
            description=(
                "Return the most recent filings from Companies House for a "
                "company. Each filing includes its date, type code, "
                "description, and category. "
                "Look for missing annual accounts, late confirmation "
                "statements, or unusual filings (e.g. voluntary strike-off "
                "applications, restorations) as risk signals."
            ),
            parameters=_obj(
                {
                    "company_number": _str("8-character Companies House company number."),
                    "limit": _int(
                        "Maximum number of recent filings to return (1-50).",
                        default=20,
                    ),
                },
                required=["company_number"],
            ),
            fn=lambda company_number, limit=20: ch.get_filing_history(
                company_number=company_number, limit=limit
            ),
        )
    )

    # ------------------------------------------------------------------
    # 5. get_psc
    # ------------------------------------------------------------------
    registry.register(
        ToolDefinition(
            name="get_psc",
            description=(
                "Return the Persons with Significant Control (PSC) register "
                "for a company: total PSC count, breakdown by kind (individual "
                "/ corporate-entity / legal-person), names of any corporate "
                "PSCs, and count of ceased PSCs. "
                "Missing PSC data, a large number of ceased PSCs, or complex "
                "offshore holding structures are risk indicators."
            ),
            parameters=_obj(
                {
                    "company_number": _str("8-character Companies House company number."),
                },
                required=["company_number"],
            ),
            fn=lambda company_number: ch.get_psc(company_number=company_number),
        )
    )

    # ------------------------------------------------------------------
    # 6. get_charges
    # ------------------------------------------------------------------
    registry.register(
        ToolDefinition(
            name="get_charges",
            description=(
                "Return registered charges (mortgages, debentures, fixed and "
                "floating charges) for a company: total count, number "
                "outstanding vs satisfied, and date of the most recent charge. "
                "Outstanding charges indicate secured creditors who rank ahead "
                "of unsecured creditors in insolvency."
            ),
            parameters=_obj(
                {
                    "company_number": _str("8-character Companies House company number."),
                },
                required=["company_number"],
            ),
            fn=lambda company_number: ch.get_charges(company_number=company_number),
        )
    )

    # ------------------------------------------------------------------
    # 7. get_insolvency
    # ------------------------------------------------------------------
    registry.register(
        ToolDefinition(
            name="get_insolvency",
            description=(
                "Return insolvency history for a company: list of insolvency "
                "cases each with type (administration, liquidation, CVA, etc.) "
                "and key dates. "
                "A 404 response means no insolvency history, which is returned "
                "as an empty list. Any insolvency case is a significant risk "
                "signal."
            ),
            parameters=_obj(
                {
                    "company_number": _str("8-character Companies House company number."),
                },
                required=["company_number"],
            ),
            fn=lambda company_number: ch.get_insolvency(company_number=company_number),
        )
    )

    # ------------------------------------------------------------------
    # 8. check_fca_register
    # ------------------------------------------------------------------
    registry.register(
        ToolDefinition(
            name="check_fca_register",
            description=(
                "Search the FCA Financial Services Register to check whether a "
                "company is authorised or registered to carry on regulated "
                "financial activities in the UK. "
                "Returns found/not-found, the firm's FCA reference number "
                "(FRN), authorisation status, and match confidence. "
                "If a company provides financial services but is not on the "
                "FCA register, that is a serious red flag."
            ),
            parameters=_obj(
                {
                    "company_name": _str("Full company name as it appears on Companies House."),
                    "company_number": _str("8-character Companies House company number."),
                },
                required=["company_name", "company_number"],
            ),
            fn=lambda company_name, company_number: fca.check_fca_register(
                company_name=company_name,
                company_number=company_number,
            ),
        )
    )

    # ------------------------------------------------------------------
    # 9. search_news
    # ------------------------------------------------------------------
    registry.register(
        ToolDefinition(
            name="search_news",
            description=(
                "Search GDELT for recent English-language news articles "
                "mentioning a company. Returns article title, URL, "
                "publication date, and domain for the most recent results. "
                "Useful for detecting adverse media coverage: fraud, scandal, "
                "sanctions, regulatory action, or financial distress. "
                "Returns ok=False silently if GDELT is unavailable — the "
                "agent should continue without news in that case."
            ),
            parameters=_obj(
                {
                    "company_name": _str("Company name to search news for."),
                    "days": _int("Look-back window in days (1-365).", default=180),
                    "limit": _int("Maximum number of articles to return (1-20).", default=5),
                },
                required=["company_name"],
            ),
            fn=lambda company_name, days=180, limit=5: news.search_news(
                company_name=company_name, days=days, limit=limit
            ),
        )
    )

    return registry


# Keep a module-level convenience alias for the return type
__all__ = ["ToolResult", "build_registry"]
