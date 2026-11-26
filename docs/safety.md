# Safety

| Risk | Control | Where |
|---|---|---|
| Runaway agent loop / cost | Per-run caps: tool calls, LLM rounds, wall time, cost; identical repeated tool calls are blocked; the run stops cleanly with a partial report and a limitation note | `agent/guards.py`, `agent/graph.py` |
| Prompt injection via tool output | Tool output is wrapped in `<tool_result>` delimiters, the system prompt says it is data, tool names are allow-listed, and the risk level is computed by code, so injected text cannot set it | `graph._wrap`, ADR-003/004 |
| Hallucinated claims | Deterministic fact check plus an LLM sentence check against the evidence; one repair attempt, then unsupported sentences are dropped and listed as limitations | `agent/claim_check.py` |
| Person-centred requests | Input filter refuses requests for home addresses, DOB, phone, criminal records, ID numbers, "who is Mr X", and rule-override phrases | `api/safety.py` |
| Abuse / spend | 10 reports/min per client IP (first `X-Forwarded-For` entry), daily budget cap (`DAILY_BUDGET_GBP`, default 0.50) → HTTP 503 | `api/ratelimit.py`, `api/budget.py` |
| Upstream limits | Client-side token bucket under the Companies House 600 requests / 5 min limit | `clients/ratelimit.py` |
| Empty 500s | A global handler returns JSON with the exception class; the SSE stream emits an `error` event | `api/main.py` |

Limits of the controls: the refusal filter is a keyword/regex list and will miss rephrased requests; the sentence check is an LLM and can be wrong in both directions (see `docs/failure_analysis.md`).
