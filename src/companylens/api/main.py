"""FastAPI app: JSON report endpoint, SSE streaming endpoint, static UI."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from companylens.agent.graph import CompanyAgent
from companylens.api.budget import DailyBudget
from companylens.api.ratelimit import SlidingWindowLimiter, client_ip
from companylens.api.safety import REFUSAL_MESSAGE, check_input
from companylens.config import AGENT_CONFIGS, DEFAULT_CONFIG, get_settings
from companylens.llm import LLMClient
from companylens.models import AgentResponse
from companylens.observability import Tracer
from companylens.tools.company_tools import build_registry
from companylens.tools.registry import ToolRegistry

log = logging.getLogger("companylens")
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="CompanyLens")
_settings = get_settings()
_limiter = SlidingWindowLimiter(limit=10, window=60.0)
_budget = DailyBudget(_settings.daily_budget_gbp)
_tracer = Tracer(_settings)
_registry: ToolRegistry | None = None
_llms: dict[str, LLMClient] = {}
_approvals: dict[str, asyncio.Future[bool]] = {}
APPROVAL_TIMEOUT_S = 120.0


class ApprovalRequest(BaseModel):
    run_id: str
    approve: bool


class ReportRequest(BaseModel):
    query: str
    config: str = DEFAULT_CONFIG


def _get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = build_registry(_settings)
    return _registry


def _make_agent(
    config_name: str, on_event: Any = None, require_approval: bool = False
) -> CompanyAgent:
    config = AGENT_CONFIGS[config_name]
    if config_name not in _llms:
        _llms[config_name] = LLMClient(config, _settings)
    return CompanyAgent(
        _get_registry(), _llms[config_name], config, _tracer, on_event, require_approval
    )


def _error(status: int, message: str, exc: BaseException | None = None) -> JSONResponse:
    body: dict[str, Any] = {"type": "error", "message": message}
    if exc is not None:
        body["exception"] = type(exc).__name__
    return JSONResponse(body, status_code=status)


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return _error(500, "Internal error while processing the request.", exc)


def _gate(request: Request, query: str, config: str) -> JSONResponse | None:
    """Apply config, rate-limit, budget and input checks; return an error response or None."""
    if config not in AGENT_CONFIGS or not AGENT_CONFIGS[config].use_agent:
        return _error(400, f"Unknown config '{config}'.")
    if not _limiter.allow(client_ip(request)):
        return _error(429, "Rate limit exceeded: 10 reports per minute. Try again shortly.")
    ok, msg = check_input(query)
    if not ok:
        refused = msg == REFUSAL_MESSAGE
        status = 200 if refused else 400
        return JSONResponse(
            AgentResponse(type="refused" if refused else "error", message=msg).model_dump(
                mode="json"
            ),
            status_code=status,
        )
    if _budget.exceeded():
        return _error(
            503, "Daily budget reached. Please try again tomorrow (resets at UTC midnight)."
        )
    return None


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness check, plus whether tracing is on and the last Langfuse HTTP status."""
    return {
        "status": "ok",
        "tracing": {"enabled": _tracer._enabled, "last_status": _tracer.last_status},
    }


@app.get("/configs")
async def configs() -> dict[str, Any]:
    """List selectable agent configurations."""
    return {
        "default": DEFAULT_CONFIG,
        "configs": {
            n: {"model": c.model, "provider": c.llm_provider, "claim_check": c.use_claim_check}
            for n, c in AGENT_CONFIGS.items()
            if c.use_agent
        },
    }


@app.post("/report")
async def report(req: ReportRequest, request: Request) -> JSONResponse:
    """Run the agent and return the full report as JSON."""
    blocked = _gate(request, req.query, req.config)
    if blocked is not None:
        return blocked
    resp = await _make_agent(req.config).run(req.query)
    if resp.report is not None:
        _budget.add(resp.report.stats.cost_gbp)
    return JSONResponse(resp.model_dump(mode="json"))


@app.get("/report/stream", response_model=None)
async def report_stream(
    request: Request,
    q: str = Query(...),
    config: str = Query(DEFAULT_CONFIG),
    approve: bool = Query(False),
) -> Any:
    """Stream agent progress and the final report as server-sent events.

    With ``approve=true`` the run pauses before third-party lookups and emits an
    ``approval_required`` event carrying a ``run_id``; answer it via ``POST /report/approve``.
    """
    blocked = _gate(request, q, config)
    if blocked is not None:
        return blocked
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    trace_id = _tracer.start_trace("report", {"query_len": len(q), "config": config})

    async def on_event(ev: dict[str, Any]) -> None:
        await queue.put(ev)

    async def worker() -> None:
        try:
            agent = _make_agent(config, on_event, approve)
            run_id = uuid.uuid4().hex
            resp = await agent.run(q, run_id)
            while resp.type == "approval_required":
                fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
                _approvals[run_id] = fut
                await queue.put(
                    {
                        "event": "approval_required",
                        "data": {
                            "run_id": run_id,
                            "message": resp.message,
                            "actions": resp.pending_actions,
                        },
                    }
                )
                try:
                    decision = await asyncio.wait_for(fut, APPROVAL_TIMEOUT_S)
                except TimeoutError:
                    decision = False
                finally:
                    _approvals.pop(run_id, None)
                resp = await agent.resume(run_id, decision)
            if resp.report is not None:
                _budget.add(resp.report.stats.cost_gbp)
            await queue.put({"event": "report", "data": resp.model_dump(mode="json")})
        except Exception as exc:
            log.exception("stream run failed")
            await queue.put(
                {
                    "event": "error",
                    "data": {"message": "The run failed.", "exception": type(exc).__name__},
                }
            )
        finally:
            _tracer.end_trace(trace_id, {"done": True})
            await queue.put(None)

    async def gen() -> AsyncIterator[dict[str, str]]:
        task = asyncio.create_task(worker())
        try:
            while (ev := await queue.get()) is not None:
                if ev["event"] in ("tool_call", "tool_result"):
                    _tracer.add_span(trace_id, f"{ev['event']}:{ev['data'].get('name')}", {})
                yield {"event": ev["event"], "data": json.dumps(ev["data"], default=str)}
        finally:
            task.cancel()

    return EventSourceResponse(gen())


@app.post("/report/approve")
async def approve_lookup(req: ApprovalRequest) -> JSONResponse:
    """Approve or skip the lookups a paused run is waiting on."""
    fut = _approvals.get(req.run_id)
    if fut is None or fut.done():
        return _error(404, "No run is waiting for approval with that id.")
    fut.set_result(req.approve)
    return JSONResponse({"type": "ok", "run_id": req.run_id, "approved": req.approve})


@app.get("/")
async def index() -> FileResponse:
    """Serve the static UI."""
    return FileResponse(STATIC / "index.html")
