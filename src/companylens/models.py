"""Core Pydantic v2 data models for CompanyLens."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class ToolResult(BaseModel):
    """Raw result from one tool call."""

    tool: str
    args: dict[str, Any]
    ok: bool
    data: dict[str, Any] | None = None
    source_url: str
    retrieved_at: datetime
    error: str | None = None


class Evidence(BaseModel):
    """A single piece of source evidence cited in a report."""

    id: str  # e.g. "e1", "e2"
    tool: str
    source_url: str
    retrieved_at: datetime
    excerpt: str  # brief human-readable summary of the relevant data


class Fact(BaseModel):
    """A verified fact about the company."""

    field: str  # e.g. "status", "accounts_overdue"
    value: str
    evidence_ids: list[str]


class RedFlagSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"


class RedFlag(BaseModel):
    """A risk signal with its evidence."""

    rule_id: str  # e.g. "R1"
    severity: RedFlagSeverity
    explanation: str
    evidence_ids: list[str]


class CompanyHeader(BaseModel):
    """Key identifying fields for the company."""

    name: str
    number: str
    status: str
    company_type: str
    incorporated: str | None = None
    sic_codes: list[str] = Field(default_factory=list)
    sic_descriptions: list[str] = Field(default_factory=list)
    registered_office_locality: str | None = None


class RunStats(BaseModel):
    """Operational metadata for a report run."""

    steps: int
    tool_calls: int
    llm_rounds: int
    input_tokens: int
    output_tokens: int
    cost_gbp: float
    latency_ms: int
    model: str
    config_name: str
    stop_reason: str  # "complete" | "step_limit" | "time_limit" | "cost_limit" | "loop_detected"
    claim_check_path: str | None = None  # "passed" | "repaired" | "dropped"; None = not run
    claim_check_failed_sentences: int = 0


class Report(BaseModel):
    """Full due-diligence report for one company."""

    company: CompanyHeader
    facts: list[Fact]
    red_flags: list[RedFlag]
    risk_level: RiskLevel
    risk_reasons: list[str]
    summary: str
    evidence: list[Evidence]
    stats: RunStats
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ClarificationOption(BaseModel):
    """One candidate when the company name is ambiguous."""

    company_number: str
    company_name: str
    status: str
    incorporated: str | None = None
    address_locality: str | None = None


class AgentResponse(BaseModel):
    """Top-level API response — either a report or a clarification request."""

    type: str  # "report" | "clarification" | "not_found" | "refused" | "error"
    report: Report | None = None
    clarification_options: list[ClarificationOption] | None = None
    message: str | None = None
