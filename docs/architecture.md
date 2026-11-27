# Architecture

CompanyLens turns a company name or number into a cited first-pass due-diligence report.

```
Browser (static UI, SSE) ──► FastAPI ──► gate ──► LangGraph agent ──► tools ──► Companies House / FCA / GDELT
                                          │            │                 ▲
                                          │            ├─ claim check    └─ same tools exposed over MCP
                                          │            └─ risk rules R1–R9 (deterministic)
                                          └─ rate limit · daily budget · refusal · config check
Langfuse (OTLP) ◄── redacted traces from every run
```

## Request path

1. **Gate** (`api/main.py`, `api/safety.py`): unknown config → 400, per-IP limit (first `X-Forwarded-For` entry, 10/min) → 429, person-centred request → refusal, daily budget spent → 503. A global handler turns any exception into JSON with the exception class, never an empty 500.
2. **Resolve**: search Companies House, pick a unique live exact match, otherwise ask for clarification or return `not_found`. An overlap guard stops the agent from picking an unrelated company for a nonexistent name.
3. **Plan / act / decide**: the LLM chooses tools (profile, officers, PSC, charges, insolvency, FCA, news) within `max_tool_calls` and `max_llm_rounds`. Tool outputs are treated as data, never as instructions (ADR-004).
4. **Risk**: `agent/risk.py` applies rules R1–R9 to tool output. The LLM does not decide the risk level (ADR-003).
5. **Report**: the LLM writes a summary from the evidence only.
6. **Claim check** (`agent/claim_check.py`): a deterministic number/fact check plus an LLM sentence check; one repair attempt, then unsupported sentences are dropped.
7. **Approval (optional)**: with `approve=true` the `tools` node calls LangGraph `interrupt()` before `search_news` / `check_fca_register`. The API emits `approval_required` with a `run_id`; `POST /report/approve {run_id, approve}` resumes the run (checkpointer: in-memory, thread id = run id). No answer within 120 s counts as Skip. A skipped lookup appears under limitations.
8. **Stream**: events (`resolve`, `plan`, `tool_call`, `tool_result`, `decision`, `report`, `error`) go to the UI over SSE.

## Components

| Area | Files |
|---|---|
| Clients with token-bucket (Companies House under 600 per 5 min), cache | `clients/` |
| Tools and registry, MCP server | `tools/`, `mcp_server/` (see `docs/mcp.md`) |
| Agent graph, guards, risk, claim check, baseline | `agent/` |
| LLM calls via the official `openai` SDK (Nebius, Mistral) | `llm.py`, `config.py` (named configs) |
| Redacting tracer, Langfuse OTLP export | `observability.py` |
| API, rate limit, budget, UI | `api/` |
| Evaluation | `eval/` (see `docs/eval_method.md`) |

## Runtime constraints

One uvicorn worker, `OMP_NUM_THREADS=1`, no LangChain or LiteLLM model wrappers. Measured peak memory under `docker run --memory=512m` is in `eval/results/memory.json`.

## Known gaps

- FCA lookups need credentials that are not configured; reports say so under limitations.
- GDELT is rate limited and often returns nothing; news coverage is partial.
