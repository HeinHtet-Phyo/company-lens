"""Async HTTP client for the FCA Financial Services Register."""

from __future__ import annotations

import difflib
from datetime import UTC, datetime
from typing import Any

import httpx

from companylens.config import get_settings
from companylens.models import ToolResult

_FCA_BASE = "https://register.fca.org.uk/services/V0.1"
_FCA_FIRM_URL = "https://register.fca.org.uk/s/firm"


def _now() -> datetime:
    return datetime.now(UTC)


async def _fca_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Make an HTTP request with 2 retries on 5xx."""
    import asyncio

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code in (500, 502, 503, 504) and attempt < 2:
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


def _name_similarity(a: str, b: str) -> float:
    """Return similarity ratio between two strings (case-insensitive)."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


class FCAClient:
    """Async client for the FCA Financial Services Register."""

    def __init__(self) -> None:
        settings = get_settings()
        self._email = settings.fca_api_email
        self._key = settings.fca_api_key
        self._client = httpx.AsyncClient(
            base_url=_FCA_BASE,
            headers={
                "X-Auth-Email": settings.fca_api_email,
                "X-Auth-Key": settings.fca_api_key,
            },
            timeout=10.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> FCAClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def check_fca_register(self, company_name: str, company_number: str) -> ToolResult:
        """Search the FCA register for a firm.

        Returns match details with confidence level. Never searches by
        individual names.
        """
        source_url = _FCA_FIRM_URL
        args: dict[str, str] = {
            "company_name": company_name,
            "company_number": company_number,
        }

        if not (self._email and self._key):
            return ToolResult(
                tool="check_fca_register",
                args=args,
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error="FCA credentials not configured",
            )

        try:
            resp = await _fca_request(
                self._client, "GET", "/Firm/Search", params={"q": company_name}
            )
        except httpx.RequestError as exc:
            return ToolResult(
                tool="check_fca_register",
                args=args,
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"{type(exc).__name__}: {exc}",
            )

        if resp.status_code != 200:
            return ToolResult(
                tool="check_fca_register",
                args=args,
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"HTTP {resp.status_code}",
            )

        raw = resp.json()
        firms = raw.get("Data", [])

        if not firms:
            return ToolResult(
                tool="check_fca_register",
                args=args,
                ok=True,
                data={"found": False, "match_confidence": "none"},
                source_url=source_url,
                retrieved_at=_now(),
            )

        # Score each firm: CH number match = high, name similarity otherwise
        best_firm: dict[str, Any] | None = None
        best_confidence = "low"
        best_reason = ""
        best_score = 0.0

        for firm in firms:
            frn = str(firm.get("FRN", ""))
            firm_name = str(firm.get("Organisation Name", ""))
            firm_ch_number = str(firm.get("Companies House Number", "") or "")

            # Check Companies House number match first
            if firm_ch_number and firm_ch_number.strip().upper() == company_number.strip().upper():
                best_firm = firm
                best_confidence = "high"
                best_reason = "Companies House number matched"
                break

            # Fall back to name similarity
            score = _name_similarity(company_name, firm_name)
            if score > best_score:
                best_score = score
                best_firm = firm
                if score >= 0.85:
                    best_confidence = "high"
                    best_reason = f"Name similarity {score:.0%}"
                elif score >= 0.60:
                    best_confidence = "medium"
                    best_reason = f"Name similarity {score:.0%}"
                else:
                    best_confidence = "low"
                    best_reason = f"Name similarity {score:.0%}"

        if best_firm is None or best_confidence == "low":
            # Low confidence — treat as not found
            return ToolResult(
                tool="check_fca_register",
                args=args,
                ok=True,
                data={"found": False, "match_confidence": "none"},
                source_url=source_url,
                retrieved_at=_now(),
            )

        frn = str(best_firm.get("FRN", ""))
        firm_source_url = f"{_FCA_FIRM_URL}?id={frn}" if frn else _FCA_FIRM_URL

        return ToolResult(
            tool="check_fca_register",
            args=args,
            ok=True,
            data={
                "found": True,
                "frn": frn,
                "firm_name": best_firm.get("Organisation Name"),
                "status": best_firm.get("Status"),
                "companies_house_number": best_firm.get("Companies House Number"),
                "match_confidence": best_confidence,
                "match_reason": best_reason,
                "source_url": firm_source_url,
            },
            source_url=firm_source_url,
            retrieved_at=_now(),
        )
