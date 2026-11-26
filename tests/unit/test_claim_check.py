"""Unit tests for check_facts_against_evidence (claim_check.py)."""

from __future__ import annotations

from datetime import datetime

from companylens.agent.claim_check import check_facts_against_evidence
from companylens.models import Evidence, Fact


def _make_evidence(ev_id: str, excerpt: str) -> Evidence:
    return Evidence(
        id=ev_id,
        tool="test_tool",
        source_url="https://example.com",
        retrieved_at=datetime(2024, 1, 1),
        excerpt=excerpt,
    )


def _make_fact(field: str, value: str, evidence_ids: list[str]) -> Fact:
    return Fact(field=field, value=value, evidence_ids=evidence_ids)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckFactsAgainstEvidence:
    def test_fact_value_present_in_excerpt_passes(self):
        evidence = [_make_evidence("e1", "The company status is active and trading normally.")]
        facts = [_make_fact("status", "active", ["e1"])]

        passed, failed = check_facts_against_evidence(facts, evidence)

        assert passed is True
        assert failed == []

    def test_fact_value_not_in_evidence_fails(self):
        evidence = [_make_evidence("e1", "The company status is dissolved.")]
        facts = [_make_fact("status", "active", ["e1"])]

        passed, failed = check_facts_against_evidence(facts, evidence)

        assert passed is False
        assert "status" in failed

    def test_no_matching_evidence_id_fails(self):
        evidence = [_make_evidence("e1", "active company")]
        facts = [_make_fact("status", "active", ["e99"])]  # e99 not in evidence

        passed, failed = check_facts_against_evidence(facts, evidence)

        assert passed is False
        assert "status" in failed

    def test_date_partial_match_year_month_passes(self):
        evidence = [_make_evidence("e1", "Incorporated on 2020-05-15 in England.")]
        # Value only has year-month → should still match via partial check
        facts = [_make_fact("incorporated", "2020-05", ["e1"])]

        passed, failed = check_facts_against_evidence(facts, evidence)

        assert passed is True
        assert failed == []

    def test_date_full_value_passes(self):
        evidence = [_make_evidence("e1", "Date of creation: 2020-05-15.")]
        facts = [_make_fact("date_of_creation", "2020-05-15", ["e1"])]

        passed, failed = check_facts_against_evidence(facts, evidence)

        assert passed is True
        assert failed == []

    def test_boolean_as_string_true_passes(self):
        evidence = [_make_evidence("e1", "Accounts overdue: True. Filing required.")]
        facts = [_make_fact("accounts_overdue", "True", ["e1"])]

        passed, failed = check_facts_against_evidence(facts, evidence)

        assert passed is True
        assert failed == []

    def test_boolean_as_string_false_passes(self):
        evidence = [_make_evidence("e1", "confirmation_statement overdue: False")]
        facts = [_make_fact("cs_overdue", "False", ["e1"])]

        passed, failed = check_facts_against_evidence(facts, evidence)

        assert passed is True
        assert failed == []

    def test_number_as_string_passes(self):
        evidence = [_make_evidence("e1", "Number of outstanding charges: 3")]
        facts = [_make_fact("outstanding_charges", "3", ["e1"])]

        passed, failed = check_facts_against_evidence(facts, evidence)

        assert passed is True
        assert failed == []

    def test_multiple_facts_mixed_results(self):
        evidence = [
            _make_evidence("e1", "status: active"),
            _make_evidence("e2", "charges: 0"),
        ]
        facts = [
            _make_fact("status", "active", ["e1"]),  # pass
            _make_fact("charges", "5", ["e2"]),  # fail - "5" not in excerpt
        ]

        passed, failed = check_facts_against_evidence(facts, evidence)

        assert passed is False
        assert "charges" in failed
        assert "status" not in failed

    def test_case_insensitive_match(self):
        evidence = [_make_evidence("e1", "Company Status: ACTIVE")]
        facts = [_make_fact("status", "active", ["e1"])]

        passed, _failed = check_facts_against_evidence(facts, evidence)

        assert passed is True

    def test_empty_facts_all_pass(self):
        evidence = [_make_evidence("e1", "some text")]
        passed, failed = check_facts_against_evidence([], evidence)

        assert passed is True
        assert failed == []

    def test_empty_evidence_all_fail(self):
        facts = [_make_fact("status", "active", ["e1"])]
        passed, failed = check_facts_against_evidence(facts, [])

        assert passed is False
        assert "status" in failed


class _J:
    def __init__(self, content: str) -> None:
        self.content = content

    async def chat(self, **kw):  # type: ignore[no-untyped-def]
        return _J(self.content), 1, 1, 0.0


async def _verdicts(content: str, summary: str):  # type: ignore[no-untyped-def]
    from companylens.agent.claim_check import check_summary_against_evidence

    return await check_summary_against_evidence(summary, [], _J(content), "m")


async def test_judge_results_wrapper_parsed() -> None:
    content = (
        '{"results": [{"sentence": "A is true.", "verdict": "supported"},'
        ' {"sentence": "B is made up.", "verdict": "unsupported"}]}'
    )
    ok, bad = await _verdicts(content, "A is true. B is made up.")
    assert ok == ["A is true."] and bad == ["B is made up."]


async def test_judge_single_object_parsed() -> None:
    ok, bad = await _verdicts('{"sentence": "A is true.", "verdict": "supported"}', "A is true.")
    assert ok == ["A is true."] and bad == []
