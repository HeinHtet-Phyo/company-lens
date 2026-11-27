"""LangGraph agent: resolve -> plan -> act <-> decide -> report."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from companylens.agent.baseline import (
    _build_company_header,
    _build_evidence,
    _build_facts,
    _extract_data,
    _load_prompt,
    limitation_for,
)
from companylens.agent.claim_check import CountingLLM as _CountingLLM
from companylens.agent.claim_check import run_claim_check
from companylens.agent.guards import AgentGuards, GuardConfig
from companylens.agent.risk import assess_risk
from companylens.agent.state import AgentState
from companylens.config import AgentConfig
from companylens.llm import LLMClient
from companylens.models import (
    AgentResponse,
    ClarificationOption,
    Report,
    RunStats,
    ToolResult,
)
from companylens.observability import Tracer
from companylens.tools.registry import ToolRegistry

_NUMBER_RE = re.compile(r"^(?=(?:.*\d){6})[A-Za-z0-9]{8}$")
_RESOLVE_PROMPT = (
    "You resolve a user's company query to one UK company. Candidates are listed as JSON. "
    'Reply with JSON: {"choice": "<company_number or null>", "ambiguous": <bool>, '
    '"reason": "<short>"}. Set ambiguous=true if two or more candidates are plausible '
    "matches for the query (e.g. a generic brand name). Set choice=null if none plausibly match."
)
_RULE_TOOL = {
    "R1": "get_company_profile",
    "R2": "get_company_profile",
    "R3": "get_company_profile",
    "R4": "get_charges",
    "R5": "get_insolvency",
    "R6": "get_company_profile",
    "R7": "get_officers",
    "R8": "check_fca_register",
    "R9": "get_psc",
}


_SUFFIXES = {"ltd", "limited", "plc", "llp", "uk"}


def _norm_name(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def _overlap(query: str, name: str) -> float:
    """Share of the query's words that appear in the candidate name."""
    qw, nw = set(query.split()), set(name.split())
    return len(qw & nw) / len(qw) if qw else 0.0


def _short(res: ToolResult) -> str:
    data = res.data or {}
    keys = [k for k in data if not isinstance(data[k], (list, dict))][:4]
    return ", ".join(f"{k}={data[k]}" for k in keys) or "ok"


def _wrap(result: ToolResult) -> str:
    """Wrap tool output as delimited data so the model treats it as untrusted."""
    body = json.dumps({"ok": result.ok, "data": result.data, "error": result.error}, default=str)
    return f'<tool_result tool="{result.tool}">\n{body[:6000]}\n</tool_result>'


class CompanyAgent:
    """Builds and runs the LangGraph investigation agent."""

    def __init__(
        self,
        registry: ToolRegistry,
        llm: LLMClient,
        config: AgentConfig,
        tracer: Tracer,
        on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.on_event = on_event
        self.registry = registry
        self.llm = llm
        self.config = config
        self.tracer = tracer
        self.guards = AgentGuards(
            GuardConfig(
                max_tool_calls=config.max_tool_calls,
                max_llm_rounds=config.max_llm_rounds,
                max_wall_seconds=float(config.max_wall_seconds),
                max_cost_gbp=config.max_cost_gbp,
            )
        )
        self.allowed = {t.name for t in registry.all_tools()}
        self.graph = self._build()

    def _build(self) -> Any:
        g = StateGraph(AgentState)
        g.add_node("resolve", self._resolve)
        g.add_node("plan", self._plan)
        g.add_node("act", self._act)
        g.add_node("decide", self._decide)
        g.add_node("report", self._report)
        g.add_edge(START, "resolve")
        g.add_conditional_edges("resolve", self._after_resolve, {"plan": "plan", "end": END})
        g.add_edge("plan", "act")
        g.add_edge("act", "decide")
        g.add_conditional_edges("decide", self._after_decide, {"act": "act", "report": "report"})
        g.add_edge("report", END)
        return g.compile()

    async def run(self, query: str) -> AgentResponse:
        """Run the agent on a company name or number."""
        state: AgentState = {
            "query": query.strip(),
            "config_name": self.config.name,
            "company_number": None,
            "company_name": None,
            "needs_clarification": False,
            "clarification_options": [],
            "investigation_plan": None,
            "tool_call_history": [],
            "tool_results": [],
            "messages": [],
            "llm_rounds": 0,
            "tool_calls_count": 0,
            "start_time": time.monotonic(),
            "cost_gbp": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "should_stop": False,
            "stop_reason": "complete",
            "pending_approval": None,
            "approval_granted": False,
            "report": None,
            "error_message": None,
        }
        out = await self.graph.ainvoke(state)
        if out.get("report") is not None:
            return AgentResponse(type="report", report=out["report"])
        if out.get("needs_clarification"):
            return AgentResponse(
                type="clarification",
                clarification_options=[
                    ClarificationOption(**o) for o in out["clarification_options"]
                ],
                message="Several companies match. Please choose one.",
            )
        return AgentResponse(
            type="not_found", message=out.get("error_message") or "No such company."
        )

    async def _emit(self, event: str, **data: Any) -> None:
        if self.on_event is not None:
            await self.on_event({"event": event, "data": data})

    async def _tool(self, name: str, **args: Any) -> ToolResult:
        """Call a tool and stream tool_call / tool_result events."""
        await self._emit("tool_call", name=name, args=args)
        res = await self._call(name, **args)
        await self._emit(
            "tool_result",
            name=name,
            ok=res.ok,
            summary=(res.error or "ok") if not res.ok else _short(res),
            source_url=res.source_url,
        )
        return res

    async def _call(self, name: str, **args: Any) -> ToolResult:
        try:
            return await self.registry.get(name).fn(**args)
        except Exception as exc:
            return ToolResult(
                tool=name,
                args=args,
                ok=False,
                source_url="",
                retrieved_at=datetime.now(UTC),
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _resolve(self, state: AgentState) -> dict[str, Any]:
        q = state["query"]
        if _NUMBER_RE.match(q):
            number = q.upper()
            res = await self._tool("get_company_profile", company_number=number)
            if not res.ok or not res.data:
                return {"error_message": f"No company found with number {number}."}
            return {
                "company_number": number,
                "company_name": str(res.data.get("company_name") or number),
                "tool_results": [res],
                "tool_call_history": [("get_company_profile", {"company_number": number})],
                "tool_calls_count": 1,
            }
        res = await self._tool("search_companies", query=q, limit=5)
        cands = (res.data or {}).get("candidates") or []
        base: dict[str, Any] = {
            "tool_results": [res],
            "tool_call_history": [("search_companies", {"query": q, "limit": 5})],
            "tool_calls_count": 1,
        }
        if not res.ok or not cands:
            return {**base, "error_message": f"No company found matching '{q}'."}
        nq = _norm_name(q)
        exact = [x for x in cands if _norm_name(x["name"] or "") == nq]
        prefix = [x for x in cands if _norm_name(x["name"] or "").startswith(nq)]
        live_exact = [x for x in exact if x.get("status") != "dissolved"]
        pool = live_exact if live_exact else exact
        live_prefix = [x for x in prefix if x.get("status") != "dissolved"]
        typed_legal_form = bool(set(re.sub(r"[^a-z0-9 ]", " ", q.lower()).split()) & _SUFFIXES)
        # A bare name ("Apple") with several live companies sharing it must be chosen by the user.
        if not typed_legal_form and len(live_prefix) >= 2:
            return {**base, **self._clarify(cands)}
        if len(pool) == 1:
            return {**base, "company_number": pool[0]["number"], "company_name": pool[0]["name"]}
        if len(prefix) >= 2:
            return {**base, **self._clarify(cands)}
        if not any(_overlap(nq, _norm_name(x["name"] or "")) >= 0.5 for x in cands):
            return {**base, "error_message": f"No company found matching '{q}'."}
        msg, i, o, c = await self.llm.chat(
            messages=[
                {"role": "system", "content": _RESOLVE_PROMPT},
                {"role": "user", "content": f"Query: {q}\nCandidates: {json.dumps(cands)}"},
            ],
            response_format={"type": "json_object"},
            model=self.config.summary_model,
        )
        base.update({"cost_gbp": state["cost_gbp"] + c, "input_tokens": i, "output_tokens": o})
        base["llm_rounds"] = state["llm_rounds"] + 1
        try:
            verdict = json.loads(msg.content or "{}")
        except json.JSONDecodeError:
            verdict = {"ambiguous": len(cands) > 1, "choice": None}
        picked = next((x for x in cands if x["number"] == verdict.get("choice")), None)
        if picked is not None and _overlap(nq, _norm_name(picked["name"] or "")) < 1.0:
            picked = None
        if verdict.get("ambiguous"):
            return {**base, **self._clarify(cands)}
        if picked is None:
            return {**base, "error_message": f"No company found matching '{q}'."}
        return {**base, "company_number": picked["number"], "company_name": picked["name"]}

    @staticmethod
    def _clarify(cands: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "needs_clarification": True,
            "clarification_options": [
                {
                    "company_number": x["number"],
                    "company_name": x["name"],
                    "status": x.get("status") or "unknown",
                    "incorporated": x.get("date_of_creation"),
                    "address_locality": x.get("address_locality"),
                }
                for x in cands
            ],
        }

    def _after_resolve(self, state: AgentState) -> Literal["plan", "end"]:
        return "plan" if state.get("company_number") else "end"

    async def _plan(self, state: AgentState) -> dict[str, Any]:
        system = _load_prompt("system.txt")
        who = f"{state['company_name']} ({state['company_number']})"
        msg, i, o, c = await self.llm.chat(
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"Company: {who}. Write a 2-3 sentence investigation plan: "
                    "which tools you will call and why.",
                },
            ],
            model=self.config.summary_model,
        )
        plan = msg.content or ""
        await self._emit(
            "resolve", company_number=state["company_number"], company_name=state["company_name"]
        )
        await self._emit("plan", text=plan)
        return {
            "investigation_plan": plan,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Investigate {who}. Plan: {plan}"},
            ],
            "llm_rounds": state["llm_rounds"] + 1,
            "cost_gbp": state["cost_gbp"] + c,
            "input_tokens": state["input_tokens"] + i,
            "output_tokens": state["output_tokens"] + o,
        }

    async def _act(self, state: AgentState) -> dict[str, Any]:
        guard = self.guards.check_all(
            state["tool_calls_count"], state["llm_rounds"], state["start_time"], state["cost_gbp"]
        )
        if not guard.allowed:
            return {"should_stop": True, "stop_reason": guard.stop_reason or "limit"}
        msg, i, o, c = await self.llm.chat(
            messages=state["messages"], tools=self.registry.to_openai_format()
        )
        upd: dict[str, Any] = {
            "llm_rounds": state["llm_rounds"] + 1,
            "cost_gbp": state["cost_gbp"] + c,
            "input_tokens": state["input_tokens"] + i,
            "output_tokens": state["output_tokens"] + o,
        }
        calls = list(getattr(msg, "tool_calls", None) or [])
        if not calls:
            upd["should_stop"] = True
            upd["stop_reason"] = "complete"
            return upd
        assistant: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in calls
            ],
        }
        history = list(state["tool_call_history"])
        count = state["tool_calls_count"]
        pending: list[tuple[str, str, dict[str, Any]]] = []
        replies: list[dict[str, Any]] = []
        for tc in calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            allowed = self.guards.check_tool_allowlist(name, self.allowed)
            loop = self.guards.check_loop_detection(name, args, history)
            if not allowed.allowed:
                replies.append(self._tool_msg(tc.id, f"Blocked: {allowed.message}"))
            elif not loop.allowed:
                replies.append(self._tool_msg(tc.id, f"Blocked: {loop.message}"))
            elif count + len(pending) >= self.config.max_tool_calls:
                replies.append(self._tool_msg(tc.id, "Blocked: tool call limit reached."))
                upd["stop_reason"] = "tool_call_limit"
            else:
                pending.append((tc.id, name, args))
                history.append((name, args))
        results = await asyncio.gather(*(self._tool(n, **a) for _, n, a in pending))
        for (call_id, _, _), res in zip(pending, results, strict=True):
            replies.append(self._tool_msg(call_id, _wrap(res)))
        upd.update(
            {
                "messages": [*state["messages"], assistant, *replies],
                "tool_results": [*state["tool_results"], *results],
                "tool_call_history": history,
                "tool_calls_count": count + len(pending),
            }
        )
        return upd

    @staticmethod
    def _tool_msg(call_id: str, content: str) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call_id, "content": content}

    async def _decide(self, state: AgentState) -> dict[str, Any]:
        guard = self.guards.check_all(
            state["tool_calls_count"], state["llm_rounds"], state["start_time"], state["cost_gbp"]
        )
        if not state["should_stop"] and not guard.allowed:
            await self._emit("decision", action="stop", reason=guard.stop_reason)
            return {"should_stop": True, "stop_reason": guard.stop_reason or "limit"}
        await self._emit("decision", action="stop" if state["should_stop"] else "continue")
        return {}

    def _after_decide(self, state: AgentState) -> Literal["act", "report"]:
        return "report" if state["should_stop"] else "act"

    async def _report(self, state: AgentState) -> dict[str, Any]:
        results = [(r.tool, r) for r in state["tool_results"] if r.tool != "search_companies"]
        number = state["company_number"] or ""
        name = state["company_name"] or number
        evidence = _build_evidence(results)
        ev_by_tool: dict[str, str] = {}
        for e in evidence:
            ev_by_tool.setdefault(e.tool, e.id)
        profile = _extract_data(results, "get_company_profile")
        officers = _extract_data(results, "get_officers")
        psc = _extract_data(results, "get_psc")
        charges = _extract_data(results, "get_charges")
        insolvency = _extract_data(results, "get_insolvency")
        fca = _extract_data(results, "check_fca_register")
        rule_map = {r: ev_by_tool[t] for r, t in _RULE_TOOL.items() if t in ev_by_tool}
        risk = assess_risk(profile, officers, psc, charges, insolvency, fca, rule_map)
        facts = _build_facts(profile, officers, psc, charges, fca, evidence)

        limitations: list[str] = []
        called = {t for t, _ in results}
        for t in ("get_company_profile", "get_insolvency", "get_charges"):
            if t not in called:
                limitations.append(f"Check not performed: {t}.")
        limitations.extend(limitation_for(r) for r in state["tool_results"] if not r.ok)
        if state["stop_reason"] != "complete":
            limitations.append(f"Run stopped early: {state['stop_reason']}.")

        ev_ctx = "\n".join(f"[{e.id}] {e.tool}: {e.excerpt}" for e in evidence)
        flags = "\n".join(f"- {f.rule_id}: {f.explanation}" for f in risk.red_flags) or "None"
        msg, i, o, c = await self.llm.chat(
            messages=[
                {"role": "system", "content": _load_prompt("system.txt")},
                {
                    "role": "user",
                    "content": f"Company: {name} ({number})\nEvidence:\n{ev_ctx}\n"
                    f"Risk level: {risk.risk_level}\nFlags:\n{flags}\n\n"
                    "Write a 3-5 sentence plain-English summary. End every sentence with an "
                    "evidence citation like [e1]. No personal data.",
                },
            ],
            model=self.config.summary_model,
        )
        rounds = state["llm_rounds"] + 1
        report = Report(
            company=_build_company_header(number, name, profile),
            facts=facts,
            red_flags=risk.red_flags,
            risk_level=risk.risk_level,
            risk_reasons=risk.risk_reasons,
            summary=msg.content or "Summary unavailable.",
            evidence=evidence,
            stats=RunStats(
                steps=rounds,
                tool_calls=state["tool_calls_count"],
                llm_rounds=rounds,
                input_tokens=state["input_tokens"] + i,
                output_tokens=state["output_tokens"] + o,
                cost_gbp=state["cost_gbp"] + c,
                latency_ms=int((time.monotonic() - state["start_time"]) * 1000),
                model=self.config.model,
                config_name=self.config.name,
                stop_reason=state["stop_reason"],
            ),
            limitations=limitations,
            generated_at=datetime.now(UTC),
        )
        if self.config.use_claim_check:
            counter = _CountingLLM(self.llm)
            report, cc = await run_claim_check(report, counter, self.config.judge_model)
            st = report.stats
            st.input_tokens += counter.input_tokens
            st.output_tokens += counter.output_tokens
            st.cost_gbp += counter.cost
            st.llm_rounds += counter.calls
            st.latency_ms = int((time.monotonic() - state["start_time"]) * 1000)
            st.claim_check_path = cc.path_taken
            st.claim_check_failed_sentences = len(cc.failed_sentences)
        return {"report": report}
