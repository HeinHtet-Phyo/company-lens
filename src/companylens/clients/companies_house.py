"""Async HTTP client for the Companies House API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from companylens.clients.ratelimit import RateLimiter
from companylens.config import get_settings
from companylens.models import ToolResult

_CH_BASE = "https://api.company-information.service.gov.uk"
_CH_PROFILE_BASE = "https://find-and-update.company-information.service.gov.uk/company"

# 600 req / 5 min ≈ 2 req/sec with burst capacity of 20
_rate_limiter = RateLimiter(rate=2.0, capacity=20.0)


def _now() -> datetime:
    return datetime.now(UTC)


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Make an HTTP request with 2 retries on 429/5xx."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            await _rate_limiter.acquire()
            resp = await client.request(method, url, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                await asyncio.sleep(2**attempt)
                continue
            return resp
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(2**attempt)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unreachable")


class CompaniesHouseClient:
    """Async client for the Companies House public data API."""

    def __init__(self) -> None:
        settings = get_settings()
        self._auth = (settings.companies_house_api_key, "")
        self._client = httpx.AsyncClient(
            base_url=_CH_BASE,
            auth=self._auth,
            timeout=10.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> CompaniesHouseClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def search_companies(self, query: str, limit: int = 5) -> ToolResult:
        """Search for companies by name. Returns candidates only."""
        url = "/search/companies"
        source_url = f"https://find-and-update.company-information.service.gov.uk/search?q={query}"
        try:
            resp = await _request(
                self._client, "GET", url, params={"q": query, "items_per_page": limit}
            )
        except httpx.RequestError as exc:
            return ToolResult(
                tool="search_companies",
                args={"query": query, "limit": limit},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=str(exc),
            )

        if resp.status_code != 200:
            return ToolResult(
                tool="search_companies",
                args={"query": query, "limit": limit},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"HTTP {resp.status_code}",
            )

        raw = resp.json()
        candidates = []
        for item in raw.get("items", []):
            addr = item.get("address", {})
            candidates.append(
                {
                    "name": item.get("title"),
                    "number": item.get("company_number"),
                    "status": item.get("company_status"),
                    "date_of_creation": item.get("date_of_creation"),
                    "address_locality": addr.get("locality") or addr.get("address_line_1"),
                }
            )

        return ToolResult(
            tool="search_companies",
            args={"query": query, "limit": limit},
            ok=True,
            data={"candidates": candidates},
            source_url=source_url,
            retrieved_at=_now(),
        )

    async def get_company_profile(self, company_number: str) -> ToolResult:
        """Get company profile. Returns selected fields only — no personal data."""
        url = f"/company/{company_number}"
        source_url = f"{_CH_PROFILE_BASE}/{company_number}"
        try:
            resp = await _request(self._client, "GET", url)
        except httpx.RequestError as exc:
            return ToolResult(
                tool="get_company_profile",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=str(exc),
            )

        if resp.status_code != 200:
            return ToolResult(
                tool="get_company_profile",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"HTTP {resp.status_code}",
            )

        raw = resp.json()
        accounts_raw = raw.get("accounts", {})
        cs_raw = raw.get("confirmation_statement", {})
        reg_office = raw.get("registered_office_address", {})

        data = {
            "status": raw.get("company_status"),
            "type": raw.get("type"),
            "date_of_creation": raw.get("date_of_creation"),
            "sic_codes": raw.get("sic_codes", []),
            "accounts": {
                "next_due": accounts_raw.get("next_due"),
                "overdue": accounts_raw.get("overdue", False),
            },
            "confirmation_statement": {
                "overdue": cs_raw.get("overdue", False),
            },
            "has_insolvency_history": raw.get("has_insolvency_history", False),
            "has_charges": raw.get("has_charges", False),
            "registered_office_locality": reg_office.get("locality")
            or reg_office.get("address_line_2"),
        }

        return ToolResult(
            tool="get_company_profile",
            args={"company_number": company_number},
            ok=True,
            data=data,
            source_url=source_url,
            retrieved_at=_now(),
        )

    async def get_officers(self, company_number: str) -> ToolResult:
        """Get officer counts only — no names, DOBs, or addresses."""
        url = f"/company/{company_number}/officers"
        source_url = f"{_CH_PROFILE_BASE}/{company_number}/officers"
        try:
            resp = await _request(self._client, "GET", url, params={"items_per_page": 100})
        except httpx.RequestError as exc:
            return ToolResult(
                tool="get_officers",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=str(exc),
            )

        if resp.status_code != 200:
            return ToolResult(
                tool="get_officers",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"HTTP {resp.status_code}",
            )

        raw = resp.json()
        items = raw.get("items", [])

        from datetime import datetime as _dt

        cutoff = _dt.now(UTC)
        one_year_ago = cutoff.replace(year=cutoff.year - 1)

        active_directors = 0
        active_secretaries = 0
        resignations_last_12m = 0

        for officer in items:
            role = officer.get("officer_role", "").lower()
            resigned_on = officer.get("resigned_on")
            is_active = resigned_on is None

            if is_active:
                if "director" in role:
                    active_directors += 1
                elif "secretary" in role:
                    active_secretaries += 1
            elif resigned_on:
                try:
                    res_dt = _dt.fromisoformat(resigned_on).replace(tzinfo=UTC)
                    if res_dt >= one_year_ago:
                        resignations_last_12m += 1
                except ValueError:
                    pass

        return ToolResult(
            tool="get_officers",
            args={"company_number": company_number},
            ok=True,
            data={
                "active_directors": active_directors,
                "active_secretaries": active_secretaries,
                "resignations_last_12m": resignations_last_12m,
            },
            source_url=source_url,
            retrieved_at=_now(),
        )

    async def get_filing_history(self, company_number: str, limit: int = 20) -> ToolResult:
        """Get recent filing history."""
        url = f"/company/{company_number}/filing-history"
        source_url = f"{_CH_PROFILE_BASE}/{company_number}/filing-history"
        try:
            resp = await _request(self._client, "GET", url, params={"items_per_page": limit})
        except httpx.RequestError as exc:
            return ToolResult(
                tool="get_filing_history",
                args={"company_number": company_number, "limit": limit},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=str(exc),
            )

        if resp.status_code != 200:
            return ToolResult(
                tool="get_filing_history",
                args={"company_number": company_number, "limit": limit},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"HTTP {resp.status_code}",
            )

        raw = resp.json()
        filings = []
        for item in raw.get("items", []):
            filings.append(
                {
                    "date": item.get("date"),
                    "type": item.get("type"),
                    "description": item.get("description"),
                    "category": item.get("category"),
                }
            )

        return ToolResult(
            tool="get_filing_history",
            args={"company_number": company_number, "limit": limit},
            ok=True,
            data={"filings": filings, "total_count": raw.get("total_count", len(filings))},
            source_url=source_url,
            retrieved_at=_now(),
        )

    async def get_psc(self, company_number: str) -> ToolResult:
        """Get persons with significant control. Returns counts and corporate entity names only."""
        url = f"/company/{company_number}/persons-with-significant-control"
        source_url = f"{_CH_PROFILE_BASE}/{company_number}/persons-with-significant-control"
        try:
            resp = await _request(self._client, "GET", url)
        except httpx.RequestError as exc:
            return ToolResult(
                tool="get_psc",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=str(exc),
            )

        if resp.status_code != 200:
            return ToolResult(
                tool="get_psc",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"HTTP {resp.status_code}",
            )

        raw = resp.json()
        items = raw.get("items", [])

        kinds: dict[str, int] = {}
        corporate_pscs: list[str] = []
        ceased_count = 0

        for item in items:
            kind = item.get("kind", "unknown")
            kinds[kind] = kinds.get(kind, 0) + 1

            if item.get("ceased_on"):
                ceased_count += 1

            # Only expose names for corporate/legal entities, not individuals
            if "corporate" in kind or "legal-person" in kind:
                name = item.get("name")
                if name:
                    corporate_pscs.append(name)

        return ToolResult(
            tool="get_psc",
            args={"company_number": company_number},
            ok=True,
            data={
                "total_count": raw.get("total_results", len(items)),
                "kinds": kinds,
                "corporate_pscs": corporate_pscs,
                "ceased_count": ceased_count,
            },
            source_url=source_url,
            retrieved_at=_now(),
        )

    async def get_charges(self, company_number: str) -> ToolResult:
        """Get company charges summary."""
        url = f"/company/{company_number}/charges"
        source_url = f"{_CH_PROFILE_BASE}/{company_number}/charges"
        try:
            resp = await _request(self._client, "GET", url)
        except httpx.RequestError as exc:
            return ToolResult(
                tool="get_charges",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=str(exc),
            )

        if resp.status_code != 200:
            return ToolResult(
                tool="get_charges",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"HTTP {resp.status_code}",
            )

        raw = resp.json()
        items = raw.get("items", [])

        outstanding = sum(1 for c in items if c.get("status") == "outstanding")
        satisfied = sum(1 for c in items if c.get("status") == "satisfied")

        # Find the latest created_on date
        latest_created_on: str | None = None
        for charge in items:
            created = charge.get("created_on")
            if created:
                if latest_created_on is None or created > latest_created_on:
                    latest_created_on = created

        return ToolResult(
            tool="get_charges",
            args={"company_number": company_number},
            ok=True,
            data={
                "total": raw.get("total_count", len(items)),
                "outstanding": outstanding,
                "satisfied": satisfied,
                "latest_created_on": latest_created_on,
            },
            source_url=source_url,
            retrieved_at=_now(),
        )

    async def get_insolvency(self, company_number: str) -> ToolResult:
        """Get insolvency history. 404 means no insolvency history."""
        url = f"/company/{company_number}/insolvency"
        source_url = f"{_CH_PROFILE_BASE}/{company_number}/insolvency"
        try:
            resp = await _request(self._client, "GET", url)
        except httpx.RequestError as exc:
            return ToolResult(
                tool="get_insolvency",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=str(exc),
            )

        if resp.status_code == 404:
            return ToolResult(
                tool="get_insolvency",
                args={"company_number": company_number},
                ok=True,
                data={"cases": []},
                source_url=source_url,
                retrieved_at=_now(),
            )

        if resp.status_code != 200:
            return ToolResult(
                tool="get_insolvency",
                args={"company_number": company_number},
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"HTTP {resp.status_code}",
            )

        raw = resp.json()
        cases = []
        for case in raw.get("cases", []):
            cases.append(
                {
                    "type": case.get("type"),
                    "dates": case.get("dates", []),
                    "practitioners": len(case.get("practitioners", [])),
                }
            )

        return ToolResult(
            tool="get_insolvency",
            args={"company_number": company_number},
            ok=True,
            data={"cases": cases},
            source_url=source_url,
            retrieved_at=_now(),
        )
