"""Async GDELT DOC 2.0 news client."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from companylens.models import ToolResult

_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _now() -> datetime:
    return datetime.now(UTC)


class NewsClient:
    """Async client for GDELT DOC 2.0 news search.

    No authentication required. On any failure the agent carries on without
    news rather than failing the whole run.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> NewsClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def search_news(self, company_name: str, days: int = 180, limit: int = 5) -> ToolResult:
        """Search GDELT for recent news about a company.

        Args:
            company_name: Company name to search. Must be an entity name, not
                a person's name.
            days: Look-back window in days.
            limit: Maximum number of articles to return.

        Returns:
            ToolResult with articles list on success, ok=False on any failure.
        """
        params = {
            "mode": "artlist",
            "format": "json",
            "q": f'"{company_name}"',
            "maxrecords": str(limit),
            "timespan": f"{days}d",
            "sort": "datedesc",
        }

        # Build source URL for reference
        from urllib.parse import urlencode

        source_url = f"{_GDELT_URL}?{urlencode(params)}"

        args = {"company_name": company_name, "days": days, "limit": limit}

        try:
            resp = await self._client.get(_GDELT_URL, params=params)
        except httpx.RequestError as exc:
            return ToolResult(
                tool="search_news",
                args=args,
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=str(exc),
            )

        if resp.status_code != 200:
            return ToolResult(
                tool="search_news",
                args=args,
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"HTTP {resp.status_code}",
            )

        try:
            raw = resp.json()
        except Exception as exc:
            return ToolResult(
                tool="search_news",
                args=args,
                ok=False,
                source_url=source_url,
                retrieved_at=_now(),
                error=f"JSON decode error: {exc}",
            )

        articles = []
        for item in raw.get("articles", []):
            articles.append(
                {
                    "url": item.get("url"),
                    "title": item.get("title"),
                    "seendate": item.get("seendate"),
                    "domain": item.get("domain"),
                }
            )

        return ToolResult(
            tool="search_news",
            args=args,
            ok=True,
            data={"articles": articles},
            source_url=source_url,
            retrieved_at=_now(),
        )
