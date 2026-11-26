# Architecture Decision Records

---

## ADR-001 — Tech stack

**Date:** 2026-11-26  
**Status:** Accepted

### Context

CompanyLens is a portfolio project for a junior AI Engineer role. It must demonstrate: agents, tool use / function calling, MCP, LangGraph, safety limits, agent evaluation, observability, cost control, and deployment to a 512 MB free-tier server.

### Decision

| Concern | Choice | Why |
|---------|--------|-----|
| Language | Python 3.11 + mypy --strict | Standard for AI Engineering roles in the UK |
| HTTP | httpx (async) | Async-native, good retry/timeout support, works with HTTPX test fixtures |
| Data models | Pydantic v2 | Industry standard; strict validation; great JSON schema generation for tool definitions |
| Tool server | MCP (official mcp Python SDK, FastMCP) | Demonstrates MCP literacy; lets any MCP client (Claude Desktop etc.) use the tools |
| Agent | LangGraph StateGraph | Shows LangGraph knowledge; supports checkpoints and human-in-the-loop interrupts |
| LLM SDK | openai Python SDK pointed at Nebius/Mistral | Avoids LiteLLM which caused OOM in Citewise (used ~240 MiB on the 512 MB free tier) |
| Main LLM | Qwen3.8-27B on Nebius (summaries/judge-in-loop: Qwen3-30B-A3B-Instruct-2507) | Tool-calling that works on the models Nebius actually served at build time; cheap enough for the $15 budget. The originally planned 235B model was not in the Nebius model list |
| Eval judge | google/gemma-3-27b-it on Nebius | Different model family from the agent, non-reasoning (a DeepSeek reasoning model timed out as a judge) |
| Comparison LLM | Mistral on mistral.ai free tier | Demonstrates multi-provider evaluation |
| API | FastAPI + SSE | Fast, async, streams agent steps live |
| UI | Static HTML/CSS/JS served by FastAPI | No React build step; works in any browser; easy to maintain |
| Observability | Langfuse via OTLP/JSON over httpx | Shows evaluation and observability literacy; fail-silent in production |
| Tests | pytest + pytest-asyncio + recorded fixtures | No network in CI; reproducible |
| Packaging | Docker python:3.11-slim, non-root | Required by Render; demonstrates production awareness |
| CI | GitHub Actions | Standard; free; supports secrets for smoke eval |
| Deploy | Render free tier | Free; Docker runtime; auto-deploy |

### Consequences

- LangGraph adds ~30-40 MB to the image; we measure under 512 MB from day one.
- If LangGraph exceeds the memory budget, replace with a hand-written state machine (see ADR-002 placeholder below) and document the finding.
- MCP over stdio means the MCP client starts the server as a subprocess on the same machine. For the Render deployment, the agent can call tools in-process via the tool registry (same functions, no subprocess overhead). Both paths are tested.

---

## ADR-002 — LangGraph vs hand-written state machine

**Date:** 2026-11-26
**Status:** Accepted — keep LangGraph

### Decision

Keep LangGraph. The threshold was "replace it if peak memory exceeds 400 MiB under `--memory=512m`". Measured peak with three live reports was 92.2 MiB (84.1 MiB idle), no OOM kill (`eval/results/memory.json`). There is no memory case for a rewrite.

### Consequences

- The image is 433 MB on disk; that is a disk figure, not a memory figure.
- The graph stays small (resolve → plan → act → decide → report) and guards live outside it in `guards.py`, so the node logic would be portable if this ever changes.

---

## ADR-003 — Risk level is deterministic, not set by the LLM

**Date:** 2026-11-26  
**Status:** Accepted

### Context

The agent uses an LLM to investigate the company and write the summary. We need a risk level (Low / Medium / High) in the report.

### Decision

The risk level is computed by `risk.py` from deterministic rules (R1–R9) applied to the tool results. The LLM never sets the risk level; it only explains it in the summary.

### Why

1. **Reproducibility:** the same facts always produce the same risk level, making it easy to unit-test and to verify in the eval.
2. **Transparency:** users and hiring managers can read the rules and understand exactly why the risk level was chosen.
3. **Safety:** an adversarial company description in the tool output cannot manipulate the risk level because the LLM doesn't control it.
4. **Easier evaluation:** fact accuracy + deterministic rules → risk level agreement should be ~100% if facts are right; any miss indicates an upstream fact error.

### Consequences

- risk.py is fully unit-tested (every rule and threshold).
- The LLM writes the `risk_reasons` explanation, but cannot change the `risk_level` value.
- If a user disagrees with the risk level, they can read the exact rule that triggered it.

---

## ADR-004 — Tool outputs are data, not instructions

**Date:** 2026-11-26  
**Status:** Accepted

Tool results are wrapped in clearly delimited blocks in the LLM prompt, and the system prompt instructs the model to treat everything inside `<tool_result>` tags as external data, not as instructions. This prevents prompt injection via tool outputs (E5 in the eval).
