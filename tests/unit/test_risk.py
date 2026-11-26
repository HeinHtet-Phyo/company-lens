"""Unit tests for the deterministic risk engine (risk.py)."""

from __future__ import annotations

from companylens.agent.risk import assess_risk
from companylens.models import RedFlagSeverity, RiskLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACTIVE_PROFILE: dict = {
    "status": "active",
    "accounts": {"overdue": False},
    "confirmation_statement": {"overdue": False},
    "has_insolvency_history": False,
    "date_of_creation": "2015-01-01",
    "sic_codes": [],
}


def _profile(**kwargs) -> dict:
    """Return an active-company profile with overrides."""
    p = dict(_ACTIVE_PROFILE)
    for k, v in kwargs.items():
        if "." in k:
            top, sub = k.split(".", 1)
            p[top] = dict(p.get(top, {}))
            p[top][sub] = v
        else:
            p[k] = v
    return p


def _assess(**kwargs):
    """Call assess_risk with sensible defaults; override via keyword args."""
    defaults = {
        "profile_data": _profile(),
        "officers_data": {"resignations_last_12m": 0},
        "psc_data": {"items": []},
        "charges_data": {"outstanding": 0},
        "insolvency_data": {"cases": []},
        "fca_data": None,
        "evidence_map": {},
    }
    defaults.update(kwargs)
    return assess_risk(**defaults)


# ---------------------------------------------------------------------------
# Individual rule tests
# ---------------------------------------------------------------------------


class TestR1AccountsOverdue:
    def test_triggered(self):
        result = _assess(profile_data=_profile(**{"accounts.overdue": True}))
        rule_ids = [f.rule_id for f in result.red_flags]
        assert "R1" in rule_ids

    def test_severity_warning(self):
        result = _assess(profile_data=_profile(**{"accounts.overdue": True}))
        flag = next(f for f in result.red_flags if f.rule_id == "R1")
        assert flag.severity == RedFlagSeverity.WARNING

    def test_not_triggered_when_not_overdue(self):
        result = _assess(profile_data=_profile(**{"accounts.overdue": False}))
        assert all(f.rule_id != "R1" for f in result.red_flags)


class TestR2ConfirmationStatementOverdue:
    def test_triggered(self):
        result = _assess(profile_data=_profile(**{"confirmation_statement.overdue": True}))
        rule_ids = [f.rule_id for f in result.red_flags]
        assert "R2" in rule_ids

    def test_severity_warning(self):
        result = _assess(profile_data=_profile(**{"confirmation_statement.overdue": True}))
        flag = next(f for f in result.red_flags if f.rule_id == "R2")
        assert flag.severity == RedFlagSeverity.WARNING


class TestR3Status:
    def test_dissolved_high(self):
        result = _assess(profile_data=_profile(status="dissolved"))
        flag = next(f for f in result.red_flags if f.rule_id == "R3")
        assert flag.severity == RedFlagSeverity.HIGH

    def test_dormant_info(self):
        result = _assess(profile_data=_profile(status="dormant"))
        flag = next(f for f in result.red_flags if f.rule_id == "R3")
        assert flag.severity == RedFlagSeverity.INFO

    def test_active_no_flag(self):
        result = _assess(profile_data=_profile(status="active"))
        assert all(f.rule_id != "R3" for f in result.red_flags)


class TestR4OutstandingCharges:
    def test_triggered(self):
        result = _assess(charges_data={"outstanding": 2})
        rule_ids = [f.rule_id for f in result.red_flags]
        assert "R4" in rule_ids

    def test_severity_warning(self):
        result = _assess(charges_data={"outstanding": 1})
        flag = next(f for f in result.red_flags if f.rule_id == "R4")
        assert flag.severity == RedFlagSeverity.WARNING

    def test_zero_charges_no_flag(self):
        result = _assess(charges_data={"outstanding": 0})
        assert all(f.rule_id != "R4" for f in result.red_flags)


class TestR5InsolvencyHistory:
    def test_triggered_via_profile(self):
        result = _assess(profile_data=_profile(has_insolvency_history=True))
        rule_ids = [f.rule_id for f in result.red_flags]
        assert "R5" in rule_ids

    def test_triggered_via_insolvency_data(self):
        result = _assess(insolvency_data={"cases": [{"type": "CVL"}]})
        rule_ids = [f.rule_id for f in result.red_flags]
        assert "R5" in rule_ids

    def test_severity_high(self):
        result = _assess(profile_data=_profile(has_insolvency_history=True))
        flag = next(f for f in result.red_flags if f.rule_id == "R5")
        assert flag.severity == RedFlagSeverity.HIGH


class TestR6IncorporatedRecently:
    def test_incorporated_6_months_ago(self):
        from datetime import date, timedelta

        six_months_ago = (date.today() - timedelta(days=180)).isoformat()
        result = _assess(profile_data=_profile(date_of_creation=six_months_ago))
        rule_ids = [f.rule_id for f in result.red_flags]
        assert "R6" in rule_ids

    def test_severity_info(self):
        from datetime import date, timedelta

        six_months_ago = (date.today() - timedelta(days=180)).isoformat()
        result = _assess(profile_data=_profile(date_of_creation=six_months_ago))
        flag = next(f for f in result.red_flags if f.rule_id == "R6")
        assert flag.severity == RedFlagSeverity.INFO

    def test_incorporated_2_years_ago_no_flag(self):
        from datetime import date, timedelta

        two_years_ago = (date.today() - timedelta(days=730)).isoformat()
        result = _assess(profile_data=_profile(date_of_creation=two_years_ago))
        assert all(f.rule_id != "R6" for f in result.red_flags)


class TestR7DirectorResignations:
    def test_two_resignations_triggered(self):
        result = _assess(officers_data={"resignations_last_12m": 2})
        rule_ids = [f.rule_id for f in result.red_flags]
        assert "R7" in rule_ids

    def test_severity_warning(self):
        result = _assess(officers_data={"resignations_last_12m": 2})
        flag = next(f for f in result.red_flags if f.rule_id == "R7")
        assert flag.severity == RedFlagSeverity.WARNING

    def test_one_resignation_no_flag(self):
        result = _assess(officers_data={"resignations_last_12m": 1})
        assert all(f.rule_id != "R7" for f in result.red_flags)


class TestR8FCA:
    def test_no_longer_authorised_high(self):
        result = _assess(
            fca_data={"found": True, "status": "No longer authorised", "match_confidence": "high"}
        )
        flag = next(f for f in result.red_flags if f.rule_id == "R8")
        assert flag.severity == RedFlagSeverity.HIGH

    def test_regulated_sic_not_found_warning(self):
        result = _assess(
            profile_data=_profile(sic_codes=["6419"]),
            fca_data={"found": False, "match_confidence": "none"},
        )
        flag = next(f for f in result.red_flags if f.rule_id == "R8")
        assert flag.severity == RedFlagSeverity.WARNING

    def test_non_financial_sic_no_fca_no_flag(self):
        result = _assess(
            profile_data=_profile(sic_codes=["47110"]),
            fca_data={"found": False, "match_confidence": "none"},
        )
        assert all(f.rule_id != "R8" for f in result.red_flags)


class TestR9OverseasCorporatePSC:
    def test_overseas_corporate_info(self):
        result = _assess(
            psc_data={
                "items": [
                    {
                        "kind": "corporate-entity-person-with-significant-control",
                        "is_overseas_corporate": True,
                    }
                ]
            }
        )
        flag = next(f for f in result.red_flags if f.rule_id == "R9")
        assert flag.severity == RedFlagSeverity.INFO

    def test_non_overseas_no_flag(self):
        result = _assess(
            psc_data={"items": [{"kind": "individual-person-with-significant-control"}]}
        )
        assert all(f.rule_id != "R9" for f in result.red_flags)


# ---------------------------------------------------------------------------
# Risk level threshold tests
# ---------------------------------------------------------------------------


class TestRiskLevelThresholds:
    def test_no_flags_low_risk(self):
        result = _assess()
        assert result.risk_level == RiskLevel.LOW

    def test_only_info_flags_low_risk(self):
        from datetime import date, timedelta

        six_months_ago = (date.today() - timedelta(days=180)).isoformat()
        result = _assess(profile_data=_profile(status="dormant", date_of_creation=six_months_ago))
        severities = {f.severity for f in result.red_flags}
        assert severities <= {RedFlagSeverity.INFO}
        assert result.risk_level == RiskLevel.LOW

    def test_only_warning_flags_medium_risk(self):
        result = _assess(
            profile_data=_profile(**{"accounts.overdue": True}),
            charges_data={"outstanding": 1},
        )
        assert result.risk_level == RiskLevel.MEDIUM

    def test_one_high_flag_high_risk(self):
        result = _assess(profile_data=_profile(status="dissolved"))
        assert result.risk_level == RiskLevel.HIGH

    def test_multiple_flags_highest_severity_wins(self):
        """Warning from R1 + High from R5 → overall HIGH."""
        result = _assess(
            profile_data=_profile(**{"accounts.overdue": True}, has_insolvency_history=True)
        )
        assert result.risk_level == RiskLevel.HIGH


class TestR8EdgeCases:
    def test_fca_not_retrieved_does_not_flag(self):
        result = _assess(profile_data=_profile(sic_codes=["6419"]), fca_data=None)
        assert "R8" not in {f.rule_id for f in result.red_flags}

    def test_low_confidence_no_longer_authorised_does_not_flag(self):
        result = _assess(
            fca_data={"found": True, "status": "No longer authorised", "match_confidence": "medium"}
        )
        assert "R8" not in {f.rule_id for f in result.red_flags}
