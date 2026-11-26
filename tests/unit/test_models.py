"""Basic smoke tests for Pydantic models."""

from datetime import datetime

from companylens.models import (
    AgentResponse,
    ClarificationOption,
    CompanyHeader,
    Evidence,
    Fact,
    RedFlag,
    RedFlagSeverity,
    Report,
    RiskLevel,
    RunStats,
    ToolResult,
)


def _now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0)


def test_tool_result_ok() -> None:
    r = ToolResult(
        tool="get_company_profile",
        args={"company_number": "12345678"},
        ok=True,
        data={"status": "active"},
        source_url="https://example.com",
        retrieved_at=_now(),
    )
    assert r.ok is True
    assert r.error is None


def test_tool_result_error() -> None:
    r = ToolResult(
        tool="get_company_profile",
        args={"company_number": "00000000"},
        ok=False,
        source_url="https://example.com",
        retrieved_at=_now(),
        error="404 Not Found",
    )
    assert r.ok is False
    assert r.data is None


def test_report_round_trip() -> None:
    report = Report(
        company=CompanyHeader(
            name="TEST LTD",
            number="12345678",
            status="active",
            company_type="ltd",
        ),
        facts=[Fact(field="status", value="active", evidence_ids=["e1"])],
        red_flags=[
            RedFlag(
                rule_id="R1",
                severity=RedFlagSeverity.WARNING,
                explanation="Accounts overdue",
                evidence_ids=["e1"],
            )
        ],
        risk_level=RiskLevel.MEDIUM,
        risk_reasons=["R1 triggered"],
        summary="TEST LTD is active but has overdue accounts [e1].",
        evidence=[
            Evidence(
                id="e1",
                tool="get_company_profile",
                source_url="https://example.com",
                retrieved_at=_now(),
                excerpt="accounts.overdue = true",
            )
        ],
        stats=RunStats(
            steps=3,
            tool_calls=2,
            llm_rounds=2,
            input_tokens=500,
            output_tokens=200,
            cost_gbp=0.001,
            latency_ms=4500,
            model="Qwen3-235B",
            config_name="agent_qwen",
            stop_reason="complete",
        ),
    )
    data = report.model_dump()
    assert data["risk_level"] == "Medium"
    assert len(data["facts"]) == 1
    assert len(data["red_flags"]) == 1


def test_agent_response_clarification() -> None:
    resp = AgentResponse(
        type="clarification",
        clarification_options=[
            ClarificationOption(
                company_number="12345678",
                company_name="APPLE RETAIL UK LTD",
                status="active",
            ),
            ClarificationOption(
                company_number="98765432",
                company_name="APPLE EUROPE LTD",
                status="active",
            ),
        ],
        message="Multiple companies match 'Apple'. Please choose one.",
    )
    assert resp.type == "clarification"
    assert len(resp.clarification_options or []) == 2
