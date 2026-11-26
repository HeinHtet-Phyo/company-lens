"""Fixed (baseline) pipeline: runs 7 tools in a fixed order then writes the report."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from companylens.agent.claim_check import CountingLLM as _CountingLLM
from companylens.agent.claim_check import run_claim_check
from companylens.agent.risk import assess_risk
from companylens.config import AgentConfig
from companylens.llm import LLMClient
from companylens.models import (
    CompanyHeader,
    Evidence,
    Fact,
    Report,
    RunStats,
    ToolResult,
)
from companylens.observability import Tracer
from companylens.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Load prompt templates
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts" / "v1"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASELINE_TOOLS = [
    "get_company_profile",
    "get_officers",
    "get_filing_history",
    "get_psc",
    "get_charges",
    "get_insolvency",
    "check_fca_register",
    "search_news",
]


def _tool_excerpt(tool_result: ToolResult) -> str:
    """Build a short human-readable excerpt from a tool result."""
    if not tool_result.ok or tool_result.data is None:
        return tool_result.error or "No data returned."
    data = tool_result.data
    # Return a compact JSON snippet (truncated to ~900 chars)
    snippet = json.dumps(data, default=str)
    return snippet[:900] + ("..." if len(snippet) > 900 else "")


def _build_evidence(results: list[tuple[str, ToolResult]]) -> list[Evidence]:
    """Convert tool results to Evidence objects with sequential IDs."""
    evidence: list[Evidence] = []
    for idx, (_, result) in enumerate(results, start=1):
        evidence.append(
            Evidence(
                id=f"e{idx}",
                tool=result.tool,
                source_url=result.source_url,
                retrieved_at=result.retrieved_at,
                excerpt=_tool_excerpt(result),
            )
        )
    return evidence


def _extract_data(results: list[tuple[str, ToolResult]], tool_name: str) -> dict[str, Any] | None:
    """Return the data dict for a named tool result, or None."""
    for name, result in results:
        if name == tool_name and result.ok and result.data is not None:
            return result.data
    return None


def _build_evidence_map(
    results: list[tuple[str, ToolResult]],
    rule_evidence: dict[str, str],
) -> dict[str, str]:
    """Return rule_id -> evidence_id mapping for risk assessment."""
    return rule_evidence


def _build_facts(
    profile_data: dict[str, Any] | None,
    officers_data: dict[str, Any] | None,
    psc_data: dict[str, Any] | None,
    charges_data: dict[str, Any] | None,
    fca_data: dict[str, Any] | None,
    evidence: list[Evidence],
) -> list[Fact]:
    """Build a list of key facts from the collected tool data."""
    facts: list[Fact] = []

    # Map tool name -> evidence id
    ev_by_tool: dict[str, str] = {e.tool: e.id for e in evidence}

    def ev(tool_name: str) -> list[str]:
        ev_id = ev_by_tool.get(tool_name)
        return [ev_id] if ev_id else []

    if profile_data:
        facts.append(
            Fact(
                field="status",
                value=str(profile_data.get("status", "unknown")),
                evidence_ids=ev("get_company_profile"),
            )
        )
        sic = profile_data.get("sic_codes") or []
        if sic:
            facts.append(
                Fact(
                    field="sic_codes",
                    value=", ".join(str(s) for s in sic),
                    evidence_ids=ev("get_company_profile"),
                )
            )
        accounts = profile_data.get("accounts") or {}
        facts.append(
            Fact(
                field="accounts_overdue",
                value=str(accounts.get("overdue", False)),
                evidence_ids=ev("get_company_profile"),
            )
        )

    if officers_data:
        facts.append(
            Fact(
                field="active_directors",
                value=str(officers_data.get("active_directors", 0)),
                evidence_ids=ev("get_officers"),
            )
        )
        facts.append(
            Fact(
                field="resignations_last_12m",
                value=str(officers_data.get("resignations_last_12m", 0)),
                evidence_ids=ev("get_officers"),
            )
        )

    if psc_data:
        facts.append(
            Fact(
                field="psc_count",
                value=str(psc_data.get("total_count", 0)),
                evidence_ids=ev("get_psc"),
            )
        )

    if charges_data:
        facts.append(
            Fact(
                field="outstanding_charges",
                value=str(charges_data.get("outstanding", 0)),
                evidence_ids=ev("get_charges"),
            )
        )

    if fca_data:
        facts.append(
            Fact(
                field="fca_status",
                value=str(fca_data.get("status", "not found")),
                evidence_ids=ev("check_fca_register"),
            )
        )

    return facts


def _build_company_header(
    company_number: str,
    company_name: str,
    profile_data: dict[str, Any] | None,
) -> CompanyHeader:
    if profile_data:
        return CompanyHeader(
            name=profile_data.get("company_name", company_name),
            number=company_number,
            status=str(profile_data.get("status", "unknown")),
            company_type=str(profile_data.get("type", "unknown")),
            incorporated=profile_data.get("date_of_creation"),
            sic_codes=profile_data.get("sic_codes") or [],
            sic_descriptions=profile_data.get("sic_descriptions") or [],
            registered_office_locality=profile_data.get("registered_office_address", {}).get(
                "locality"
            ),
        )
    return CompanyHeader(
        name=company_name,
        number=company_number,
        status="unknown",
        company_type="unknown",
    )


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


async def run_baseline(
    company_number: str,
    company_name: str,
    registry: ToolRegistry,
    llm_client: LLMClient,
    config: AgentConfig,
    tracer: Tracer,
) -> Report:
    """Fixed pipeline: always calls profile, officers, filing_history, psc, charges,
    insolvency, fca, news. Then runs risk.assess_risk(), writes summary with LLM,
    then runs claim_check. Returns a Report with config_name='baseline_fixed' and
    stop_reason='complete'.
    """
    start_ms = time.time()
    trace_id = tracer.start_trace(
        "baseline_pipeline",
        {"company_number": company_number, "company_name": company_name},
    )

    results: list[tuple[str, ToolResult]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost_gbp = 0.0
    tool_calls = 0

    # ------------------------------------------------------------------
    # Fixed tool execution sequence
    # ------------------------------------------------------------------
    for tool_name in _BASELINE_TOOLS:
        try:
            defn = registry.get(tool_name)
        except KeyError:
            continue

        span_id = tracer.add_span(
            trace_id, f"tool:{tool_name}", {"tool": tool_name, "company_number": company_number}
        )

        try:
            if tool_name in {
                "get_company_profile",
                "get_officers",
                "get_filing_history",
                "get_psc",
                "get_charges",
                "get_insolvency",
            }:
                result: ToolResult = await defn.fn(company_number=company_number)
            elif tool_name == "check_fca_register":
                result = await defn.fn(company_name=company_name, company_number=company_number)
            elif tool_name == "search_news":
                result = await defn.fn(company_name=company_name)
            else:
                continue

            results.append((tool_name, result))
            tool_calls += 1
            tracer.end_span(trace_id, span_id, {"ok": result.ok})
        except Exception as exc:
            tracer.end_span(trace_id, span_id, {"error": str(exc)})

    # ------------------------------------------------------------------
    # Build evidence list
    # ------------------------------------------------------------------
    evidence = _build_evidence(results)

    # ------------------------------------------------------------------
    # Extract data for risk assessment
    # ------------------------------------------------------------------
    profile_data = _extract_data(results, "get_company_profile")
    officers_data = _extract_data(results, "get_officers")
    psc_data = _extract_data(results, "get_psc")
    charges_data = _extract_data(results, "get_charges")
    insolvency_data = _extract_data(results, "get_insolvency")
    fca_data = _extract_data(results, "check_fca_register")

    # Build rule -> evidence_id map (use first evidence id per tool)
    ev_by_tool: dict[str, str] = {e.tool: e.id for e in evidence}
    rule_evidence_map: dict[str, str] = {
        "R1": ev_by_tool.get("get_company_profile", ""),
        "R2": ev_by_tool.get("get_company_profile", ""),
        "R3": ev_by_tool.get("get_company_profile", ""),
        "R4": ev_by_tool.get("get_charges", ""),
        "R5": ev_by_tool.get("get_insolvency", ev_by_tool.get("get_company_profile", "")),
        "R6": ev_by_tool.get("get_company_profile", ""),
        "R7": ev_by_tool.get("get_officers", ""),
        "R8": ev_by_tool.get("check_fca_register", ""),
        "R9": ev_by_tool.get("get_psc", ""),
    }
    # Remove empty strings
    rule_evidence_map = {k: v for k, v in rule_evidence_map.items() if v}

    # ------------------------------------------------------------------
    # Risk assessment (deterministic — no LLM)
    # ------------------------------------------------------------------
    risk_span_id = tracer.add_span(trace_id, "risk_assessment", {})
    risk_assessment = assess_risk(
        profile_data=profile_data,
        officers_data=officers_data,
        psc_data=psc_data,
        charges_data=charges_data,
        insolvency_data=insolvency_data,
        fca_data=fca_data,
        evidence_map=rule_evidence_map,
    )
    tracer.end_span(trace_id, risk_span_id, {"risk_level": str(risk_assessment.risk_level)})

    # ------------------------------------------------------------------
    # Build facts
    # ------------------------------------------------------------------
    facts = _build_facts(profile_data, officers_data, psc_data, charges_data, fca_data, evidence)

    # ------------------------------------------------------------------
    # LLM summary generation
    # ------------------------------------------------------------------
    system_prompt = _load_prompt("system.txt")
    # report.txt is loaded for use in future agent integration; baseline uses plain summary
    _load_prompt("report.txt")

    # Compose evidence context for LLM
    evidence_context = "\n".join(f"[{e.id}] {e.tool}: {e.excerpt}" for e in evidence)
    flags_context = "\n".join(
        f"- {f.rule_id} ({f.severity}): {f.explanation}" for f in risk_assessment.red_flags
    )
    risk_context = (
        f"Risk Level: {risk_assessment.risk_level}\n"
        f"Red Flags:\n{flags_context if flags_context else 'None'}"
    )

    summary_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Company: {company_name} ({company_number})\n\n"
                f"Evidence collected:\n{evidence_context}\n\n"
                f"{risk_context}\n\n"
                "Write a 3-5 sentence plain-English summary for this company due-diligence report. "
                "Every sentence must end with a citation in square brackets, e.g. [e1]. "
                "Do not include any personal data."
            ),
        },
    ]

    llm_span_id = tracer.add_span(trace_id, "llm:summary", {"model": config.summary_model})
    summary_message, in_tok, out_tok, cost = await llm_client.chat(
        messages=summary_messages,
        temperature=0.0,
        model=config.summary_model,
    )
    total_input_tokens += in_tok
    total_output_tokens += out_tok
    total_cost_gbp += cost
    tracer.end_span(trace_id, llm_span_id, {"output_tokens": out_tok})

    summary_text = summary_message.content or "Summary unavailable."

    llm_rounds = 1

    # ------------------------------------------------------------------
    # Assemble report
    # ------------------------------------------------------------------
    latency_ms = int((time.time() - start_ms) * 1000)
    company_header = _build_company_header(company_number, company_name, profile_data)

    report = Report(
        company=company_header,
        facts=facts,
        red_flags=risk_assessment.red_flags,
        risk_level=risk_assessment.risk_level,
        risk_reasons=risk_assessment.risk_reasons,
        summary=summary_text,
        evidence=evidence,
        stats=RunStats(
            steps=len(_BASELINE_TOOLS),
            tool_calls=tool_calls,
            llm_rounds=llm_rounds,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cost_gbp=total_cost_gbp,
            latency_ms=latency_ms,
            model=config.model,
            config_name="baseline_fixed",
            stop_reason="complete",
        ),
        limitations=[
            "This is a baseline fixed-pipeline report. No adaptive agent reasoning was applied.",
            "News search results depend on GDELT availability.",
        ],
        generated_at=datetime.now(tz=UTC),
    )

    if config.use_claim_check:
        counter = _CountingLLM(llm_client)
        report, cc = await run_claim_check(report, counter, config.judge_model)
        st = report.stats
        st.input_tokens += counter.input_tokens
        st.output_tokens += counter.output_tokens
        st.cost_gbp += counter.cost
        st.llm_rounds += counter.calls
        st.latency_ms = int((time.time() - start_ms) * 1000)
        st.claim_check_path = cc.path_taken
        st.claim_check_failed_sentences = len(cc.failed_sentences)
        total_cost_gbp = st.cost_gbp

    tracer.end_trace(trace_id, {"risk_level": str(report.risk_level), "cost_gbp": total_cost_gbp})
    return report
