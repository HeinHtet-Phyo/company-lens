"""Risk engine on recorded real-company fixtures (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from companylens.agent.risk import assess_risk

FIX = json.loads((Path(__file__).parents[1] / "fixtures" / "companies.json").read_text())


def _d(tool: str, number: str) -> dict | None:  # type: ignore[type-arg]
    for k, v in FIX.items():
        if k.startswith(tool + "|") and f'"{number}"' in k and v["ok"]:
            return v["data"]  # type: ignore[no-any-return]
    return None


def _risk(number: str):  # type: ignore[no-untyped-def]
    return assess_risk(
        _d("get_company_profile", number),
        _d("get_officers", number),
        _d("get_psc", number),
        _d("get_charges", number),
        _d("get_insolvency", number),
        None,
        {},
    )


def test_company_in_administration_is_high() -> None:
    assert str(_risk("07712220").risk_level) == "High"  # NMC Health PLC


def test_fixture_companies_all_score() -> None:
    for n in ["00445790", "09446231", "00502851", "02468686", "07524813", "01833679"]:
        assert str(_risk(n).risk_level) in {"Low", "Medium", "High"}
