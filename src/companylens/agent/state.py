"""LangGraph agent state definition for CompanyLens."""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

from companylens.models import Report, ToolResult


class AgentState(TypedDict):
    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    query: str
    config_name: str

    # ------------------------------------------------------------------
    # Company resolution
    # ------------------------------------------------------------------
    company_number: str | None
    company_name: str | None
    needs_clarification: bool
    clarification_options: list[dict[str, Any]]

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------
    investigation_plan: str | None

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------
    tool_call_history: list[tuple[str, dict[str, Any]]]  # (name, args) pairs
    tool_results: list[ToolResult]  # all results so far

    # ------------------------------------------------------------------
    # LLM messages (LangGraph message accumulation)
    # ------------------------------------------------------------------
    messages: list[dict[str, Any]]

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------
    llm_rounds: int
    tool_calls_count: int
    start_time: float
    cost_gbp: float
    input_tokens: int
    output_tokens: int

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------
    should_stop: bool
    stop_reason: str

    # ------------------------------------------------------------------
    # Human approval
    # ------------------------------------------------------------------
    pending_approval: dict[str, Any] | None  # None = no pending approval
    approval_granted: bool

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    report: Report | None
    error_message: str | None
