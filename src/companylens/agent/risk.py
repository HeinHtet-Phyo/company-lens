"""Deterministic risk rules for CompanyLens. No LLM involved."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from companylens.models import RedFlag, RedFlagSeverity, RiskLevel

# ---------------------------------------------------------------------------
# Rule identifiers
# ---------------------------------------------------------------------------
R1 = "R1"  # accounts overdue
R2 = "R2"  # confirmation statement overdue
R3 = "R3"  # status not "active"
R4 = "R4"  # outstanding charges
R5 = "R5"  # insolvency history
R6 = "R6"  # incorporated less than 12 months ago
R7 = "R7"  # 2+ director resignations in last 12 months
R8 = "R8"  # FCA "no longer authorised" or missing when regulated SIC
R9 = "R9"  # corporate PSC registered overseas

# ---------------------------------------------------------------------------
# SIC helpers
# ---------------------------------------------------------------------------

REGULATED_SIC_PREFIXES = [
    "6411",
    "6419",
    "6420",
    "6430",
    "6491",
    "6499",
    "6511",
    "6512",
    "6519",
    "6520",
    "6530",
    "6611",
    "6612",
    "6619",
    "6621",
    "6622",
    "6629",
    "6630",
]


def is_financial_services_sic(sic_codes: list[str]) -> bool:
    """Return True if any SIC code has a prefix in REGULATED_SIC_PREFIXES."""
    for code in sic_codes:
        for prefix in REGULATED_SIC_PREFIXES:
            if code.startswith(prefix):
                return True
    return False


# ---------------------------------------------------------------------------
# Assessment result
# ---------------------------------------------------------------------------


@dataclass
class RiskAssessment:
    risk_level: RiskLevel
    red_flags: list[RedFlag] = field(default_factory=list)
    risk_reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HIGH_STATUS_KEYWORDS = {
    "dissolved",
    "liquidation",
    "administration",
    "receivership",
    "in-administration",
    "in-liquidation",
    "in-receivership",
    "voluntary-arrangement",
    "converted-closed",
    "petition-to-restore-dissolved",
}

_INFO_STATUS_KEYWORDS = {"dormant"}


def _months_since(date_str: str, now: date | None = None) -> float:
    """Return approximate months between *date_str* (YYYY-MM-DD) and *now*."""
    if now is None:
        now = datetime.now(tz=UTC).date()
    try:
        inc = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return float("inf")
    delta = now - inc
    return delta.days / 30.44


def _derive_risk_level(flags: list[RedFlag]) -> RiskLevel:
    severities = {f.severity for f in flags}
    if RedFlagSeverity.HIGH in severities:
        return RiskLevel.HIGH
    if RedFlagSeverity.WARNING in severities:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _ev(rule_id: str, evidence_map: dict[str, str]) -> list[str]:
    """Return evidence ids for a rule, or empty list."""
    ev_id = evidence_map.get(rule_id)
    return [ev_id] if ev_id else []


# ---------------------------------------------------------------------------
# Main assess_risk function
# ---------------------------------------------------------------------------


def assess_risk(
    profile_data: dict[str, Any] | None,
    officers_data: dict[str, Any] | None,
    psc_data: dict[str, Any] | None,
    charges_data: dict[str, Any] | None,
    insolvency_data: dict[str, Any] | None,
    fca_data: dict[str, Any] | None,
    evidence_map: dict[str, str],  # rule_id → evidence_id
) -> RiskAssessment:
    """Apply all nine deterministic risk rules and return a RiskAssessment."""

    flags: list[RedFlag] = []

    # ------------------------------------------------------------------
    # R1 - Accounts overdue
    # ------------------------------------------------------------------
    if profile_data:
        accounts = profile_data.get("accounts") or {}
        if accounts.get("overdue") is True:
            flags.append(
                RedFlag(
                    rule_id=R1,
                    severity=RedFlagSeverity.WARNING,
                    explanation="Company accounts are overdue at Companies House.",
                    evidence_ids=_ev(R1, evidence_map),
                )
            )

        # ------------------------------------------------------------------
        # R2 - Confirmation statement overdue
        # ------------------------------------------------------------------
        cs = profile_data.get("confirmation_statement") or {}
        if cs.get("overdue") is True:
            flags.append(
                RedFlag(
                    rule_id=R2,
                    severity=RedFlagSeverity.WARNING,
                    explanation="Confirmation statement is overdue at Companies House.",
                    evidence_ids=_ev(R2, evidence_map),
                )
            )

        # ------------------------------------------------------------------
        # R3 - Status not "active"
        # ------------------------------------------------------------------
        raw_status: str = str(profile_data.get("status") or "").lower()
        if raw_status and raw_status != "active":
            if raw_status in _INFO_STATUS_KEYWORDS:
                severity = RedFlagSeverity.INFO
                explanation = f"Company status is '{raw_status}' (dormant)."
            else:
                severity = RedFlagSeverity.HIGH
                explanation = (
                    f"Company status is '{raw_status}', indicating it may no longer be trading."
                )
            flags.append(
                RedFlag(
                    rule_id=R3,
                    severity=severity,
                    explanation=explanation,
                    evidence_ids=_ev(R3, evidence_map),
                )
            )

        # ------------------------------------------------------------------
        # R5 - Insolvency history (from profile)
        # ------------------------------------------------------------------
        if profile_data.get("has_insolvency_history") is True:
            flags.append(
                RedFlag(
                    rule_id=R5,
                    severity=RedFlagSeverity.HIGH,
                    explanation="Companies House records indicate a history of insolvency.",
                    evidence_ids=_ev(R5, evidence_map),
                )
            )

        # ------------------------------------------------------------------
        # R6 - Incorporated less than 12 months ago
        # ------------------------------------------------------------------
        incorporated: str | None = profile_data.get("date_of_creation") or profile_data.get(
            "incorporated"
        )
        if incorporated and _months_since(incorporated) < 12:
            flags.append(
                RedFlag(
                    rule_id=R6,
                    severity=RedFlagSeverity.INFO,
                    explanation=(
                        f"Company was incorporated on {incorporated}, "
                        f"less than 12 months ago. Limited trading history available."
                    ),
                    evidence_ids=_ev(R6, evidence_map),
                )
            )

    # ------------------------------------------------------------------
    # R4 - Outstanding charges
    # ------------------------------------------------------------------
    if charges_data:
        outstanding = charges_data.get("outstanding", 0) or 0
        if outstanding > 0:
            flags.append(
                RedFlag(
                    rule_id=R4,
                    severity=RedFlagSeverity.WARNING,
                    explanation=f"Company has {outstanding} outstanding charge(s) registered at Companies House.",
                    evidence_ids=_ev(R4, evidence_map),
                )
            )

    # ------------------------------------------------------------------
    # R5 - Insolvency cases (from insolvency endpoint)
    # ------------------------------------------------------------------
    if insolvency_data:
        cases = insolvency_data.get("cases") or []
        if cases:
            # Only add if not already added from profile_data
            already = any(f.rule_id == R5 for f in flags)
            if not already:
                flags.append(
                    RedFlag(
                        rule_id=R5,
                        severity=RedFlagSeverity.HIGH,
                        explanation=f"Insolvency data records {len(cases)} insolvency case(s).",
                        evidence_ids=_ev(R5, evidence_map),
                    )
                )

    # ------------------------------------------------------------------
    # R7 - 2+ director resignations in last 12 months
    # ------------------------------------------------------------------
    if officers_data:
        resignations = officers_data.get("resignations_last_12m", 0) or 0
        if resignations >= 2:
            flags.append(
                RedFlag(
                    rule_id=R7,
                    severity=RedFlagSeverity.WARNING,
                    explanation=(
                        f"{resignations} director(s) resigned in the past 12 months, "
                        "which may indicate instability in management."
                    ),
                    evidence_ids=_ev(R7, evidence_map),
                )
            )

    # ------------------------------------------------------------------
    # R8 - FCA status
    # ------------------------------------------------------------------
    sic_codes: list[str] = []
    if profile_data:
        sic_codes = profile_data.get("sic_codes") or []

    if fca_data:
        fca_status: str = str(fca_data.get("status") or "").lower()
        fca_confident: bool = fca_data.get("match_confidence") == "high"
        fca_not_found: bool = fca_data.get("found") is False

        if "no longer authorised" in fca_status and fca_confident:
            flags.append(
                RedFlag(
                    rule_id=R8,
                    severity=RedFlagSeverity.HIGH,
                    explanation=(
                        "FCA register shows this firm is 'No longer authorised'. "
                        "It may not currently hold the permissions it previously had."
                    ),
                    evidence_ids=_ev(R8, evidence_map),
                )
            )
        elif fca_not_found and is_financial_services_sic(sic_codes):
            flags.append(
                RedFlag(
                    rule_id=R8,
                    severity=RedFlagSeverity.WARNING,
                    explanation=(
                        "Company has a financial-services SIC code but no FCA registration was found. "
                        "It may require FCA authorisation."
                    ),
                    evidence_ids=_ev(R8, evidence_map),
                )
            )

    # ------------------------------------------------------------------
    # R9 - Corporate PSC registered overseas
    # ------------------------------------------------------------------
    if psc_data:
        persons = psc_data.get("items") or []
        for psc in persons:
            if psc.get("is_overseas_corporate") is True:
                flags.append(
                    RedFlag(
                        rule_id=R9,
                        severity=RedFlagSeverity.INFO,
                        explanation=(
                            "One or more persons with significant control (PSC) are "
                            "overseas-incorporated corporate entities."
                        ),
                        evidence_ids=_ev(R9, evidence_map),
                    )
                )
                break  # one flag per rule is enough

    # ------------------------------------------------------------------
    # Derive overall risk level and reasons
    # ------------------------------------------------------------------
    risk_level = _derive_risk_level(flags)
    risk_reasons = [f.explanation for f in flags]

    return RiskAssessment(
        risk_level=risk_level,
        red_flags=flags,
        risk_reasons=risk_reasons,
    )
