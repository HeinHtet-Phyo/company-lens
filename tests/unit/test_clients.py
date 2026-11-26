"""Tests for HTTP clients using recorded fixtures (no live network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from companylens.clients.companies_house import CompaniesHouseClient
from companylens.clients.fca import FCAClient
from companylens.clients.news import NewsClient

# ---------------------------------------------------------------------------
# Fixture data (inline — mirrors what real APIs return, trimmed)
# ---------------------------------------------------------------------------

SEARCH_COMPANIES_FIXTURE: dict[str, Any] = {
    "items": [
        {
            "title": "ACME WIDGETS LTD",
            "company_number": "12345678",
            "company_status": "active",
            "date_of_creation": "2015-03-10",
            "address": {"locality": "London", "address_line_1": "123 High Street"},
        },
        {
            "title": "ACME HOLDINGS LTD",
            "company_number": "87654321",
            "company_status": "dissolved",
            "date_of_creation": "2008-07-22",
            "address": {"locality": "Manchester"},
        },
    ]
}

GET_COMPANY_PROFILE_ACTIVE_FIXTURE: dict[str, Any] = {
    "company_status": "active",
    "type": "ltd",
    "date_of_creation": "2015-03-10",
    "sic_codes": ["62012", "62020"],
    "accounts": {"next_due": "2025-12-31", "overdue": False},
    "confirmation_statement": {"overdue": False},
    "has_insolvency_history": False,
    "has_charges": True,
    "registered_office_address": {"locality": "London"},
}

GET_COMPANY_PROFILE_DISSOLVED_FIXTURE: dict[str, Any] = {
    "company_status": "dissolved",
    "type": "ltd",
    "date_of_creation": "2008-07-22",
    "sic_codes": ["47710"],
    "accounts": {"next_due": None, "overdue": False},
    "confirmation_statement": {"overdue": False},
    "has_insolvency_history": False,
    "has_charges": False,
    "registered_office_address": {"locality": "Manchester"},
}

GET_INSOLVENCY_404_FIXTURE: None = None  # 404 → no body needed

GET_INSOLVENCY_ACTIVE_FIXTURE: dict[str, Any] = {
    "cases": [
        {
            "type": "creditors-voluntary-liquidation",
            "dates": [{"type": "wound-up-on", "date": "2023-01-15"}],
            "practitioners": [{"name": "John Smith IP"}],
        }
    ]
}

GET_CHARGES_FIXTURE: dict[str, Any] = {
    "total_count": 2,
    "items": [
        {"status": "outstanding", "created_on": "2022-05-01"},
        {"status": "satisfied", "created_on": "2018-11-20"},
    ],
}

GET_PSC_CORPORATE_FIXTURE: dict[str, Any] = {
    "total_results": 2,
    "items": [
        {
            "kind": "corporate-entity-person-with-significant-control",
            "name": "BIGCORP HOLDINGS PLC",
            "ceased_on": None,
        },
        {
            "kind": "individual-person-with-significant-control",
            "name": "Jane Doe",  # individual — should be suppressed
            "ceased_on": "2023-06-01",
        },
    ],
}

FCA_MATCH_FOUND_FIXTURE: dict[str, Any] = {
    "Data": [
        {
            "FRN": "123456",
            "Organisation Name": "ACME WIDGETS LTD",
            "Status": "Authorised",
            "Companies House Number": "12345678",
        }
    ]
}

FCA_NOT_FOUND_FIXTURE: dict[str, Any] = {"Data": []}

GDELT_ARTICLES_FIXTURE: dict[str, Any] = {
    "articles": [
        {
            "url": "https://example.com/news/1",
            "title": "ACME WIDGETS announces expansion",
            "seendate": "20250101T120000Z",
            "domain": "example.com",
            "extra_field": "should be stripped",
        }
    ]
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CH_BASE = "https://api.company-information.service.gov.uk"
_FCA_BASE = "https://register.fca.org.uk/services/V0.1"
_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _mock_settings() -> Any:
    """Return a fake settings object."""
    from unittest.mock import MagicMock

    s = MagicMock()
    s.companies_house_api_key = "test-ch-key"
    s.fca_api_email = "test@example.com"
    s.fca_api_key = "test-fca-key"
    return s


# ---------------------------------------------------------------------------
# Companies House — search_companies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_companies_returns_candidates(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CH_BASE}/search/companies?q=ACME&items_per_page=5",
        json=SEARCH_COMPANIES_FIXTURE,
    )

    with patch("companylens.clients.companies_house.get_settings", _mock_settings):
        async with CompaniesHouseClient() as client:
            result = await client.search_companies("ACME", limit=5)

    assert result.ok is True
    assert result.data is not None
    candidates = result.data["candidates"]
    assert len(candidates) == 2
    assert candidates[0]["name"] == "ACME WIDGETS LTD"
    assert candidates[0]["number"] == "12345678"
    assert candidates[1]["status"] == "dissolved"


# ---------------------------------------------------------------------------
# Companies House — get_company_profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_company_profile_active(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CH_BASE}/company/12345678",
        json=GET_COMPANY_PROFILE_ACTIVE_FIXTURE,
    )

    with patch("companylens.clients.companies_house.get_settings", _mock_settings):
        async with CompaniesHouseClient() as client:
            result = await client.get_company_profile("12345678")

    assert result.ok is True
    assert result.data is not None
    assert result.data["status"] == "active"
    assert result.data["has_charges"] is True
    assert result.data["accounts"]["overdue"] is False


@pytest.mark.asyncio
async def test_get_company_profile_dissolved(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CH_BASE}/company/87654321",
        json=GET_COMPANY_PROFILE_DISSOLVED_FIXTURE,
    )

    with patch("companylens.clients.companies_house.get_settings", _mock_settings):
        async with CompaniesHouseClient() as client:
            result = await client.get_company_profile("87654321")

    assert result.ok is True
    assert result.data is not None
    assert result.data["status"] == "dissolved"
    assert result.data["has_charges"] is False


# ---------------------------------------------------------------------------
# Companies House — get_insolvency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_insolvency_404_returns_empty_cases(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CH_BASE}/company/12345678/insolvency",
        status_code=404,
    )

    with patch("companylens.clients.companies_house.get_settings", _mock_settings):
        async with CompaniesHouseClient() as client:
            result = await client.get_insolvency("12345678")

    assert result.ok is True
    assert result.data is not None
    assert result.data["cases"] == []


@pytest.mark.asyncio
async def test_get_insolvency_non_200_returns_error(httpx_mock: HTTPXMock) -> None:
    # 403 does not trigger retries — one request, one response
    httpx_mock.add_response(
        url=f"{_CH_BASE}/company/12345678/insolvency",
        status_code=403,
    )

    with patch("companylens.clients.companies_house.get_settings", _mock_settings):
        async with CompaniesHouseClient() as client:
            result = await client.get_insolvency("12345678")

    assert result.ok is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Companies House — get_charges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_charges_outstanding(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CH_BASE}/company/12345678/charges",
        json=GET_CHARGES_FIXTURE,
    )

    with patch("companylens.clients.companies_house.get_settings", _mock_settings):
        async with CompaniesHouseClient() as client:
            result = await client.get_charges("12345678")

    assert result.ok is True
    assert result.data is not None
    assert result.data["total"] == 2
    assert result.data["outstanding"] == 1
    assert result.data["satisfied"] == 1
    assert result.data["latest_created_on"] == "2022-05-01"


# ---------------------------------------------------------------------------
# Companies House — get_psc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_psc_corporate_names_exposed(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CH_BASE}/company/12345678/persons-with-significant-control",
        json=GET_PSC_CORPORATE_FIXTURE,
    )

    with patch("companylens.clients.companies_house.get_settings", _mock_settings):
        async with CompaniesHouseClient() as client:
            result = await client.get_psc("12345678")

    assert result.ok is True
    assert result.data is not None
    # Corporate entity name should appear
    assert "BIGCORP HOLDINGS PLC" in result.data["corporate_pscs"]
    # Individual name must NOT appear
    assert "Jane Doe" not in result.data["corporate_pscs"]
    # Ceased count
    assert result.data["ceased_count"] == 1


# ---------------------------------------------------------------------------
# FCA — check_fca_register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fca_check_match_found_high_confidence(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_FCA_BASE}/Firm/Search?q=ACME+WIDGETS+LTD",
        json=FCA_MATCH_FOUND_FIXTURE,
    )

    with patch("companylens.clients.fca.get_settings", _mock_settings):
        async with FCAClient() as client:
            result = await client.check_fca_register("ACME WIDGETS LTD", "12345678")

    assert result.ok is True
    assert result.data is not None
    assert result.data["found"] is True
    assert result.data["match_confidence"] == "high"
    assert result.data["frn"] == "123456"


@pytest.mark.asyncio
async def test_fca_check_not_found(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_FCA_BASE}/Firm/Search?q=UNKNOWN+CO+LTD",
        json=FCA_NOT_FOUND_FIXTURE,
    )

    with patch("companylens.clients.fca.get_settings", _mock_settings):
        async with FCAClient() as client:
            result = await client.check_fca_register("UNKNOWN CO LTD", "99999999")

    assert result.ok is True
    assert result.data is not None
    assert result.data["found"] is False
    assert result.data["match_confidence"] == "none"


# ---------------------------------------------------------------------------
# News — search_news
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_news_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        json=GDELT_ARTICLES_FIXTURE,
    )

    async with NewsClient() as client:
        result = await client.search_news("ACME WIDGETS LTD", days=30, limit=5)

    assert result.ok is True
    assert result.data is not None
    articles = result.data["articles"]
    assert len(articles) == 1
    assert articles[0]["title"] == "ACME WIDGETS announces expansion"
    # Extra field should be stripped
    assert "extra_field" not in articles[0]


@pytest.mark.asyncio
async def test_search_news_failure_non_200_ok_false(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        status_code=429,
    )

    async with NewsClient() as client:
        result = await client.search_news("ACME WIDGETS LTD", days=30, limit=5)

    # Agent must be able to carry on — no exception, just ok=False
    assert result.ok is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_search_news_network_error_ok_false(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectTimeout("timeout"))

    async with NewsClient() as client:
        result = await client.search_news("ACME WIDGETS LTD", days=30, limit=5)

    assert result.ok is False
    assert result.error is not None
