# CompanyLens — Build Plan

**Last updated:** 2026-11-26  
**Spend so far:** $0.00  
**Branch:** main

---

## Phase 0 — Scaffold ✅ IN PROGRESS
- [x] CLAUDE.md
- [x] PLAN.md
- [x] Directory structure
- [x] pyproject.toml
- [x] Makefile
- [x] .env.example
- [x] .gitignore (expanded)
- [x] src/companylens/models.py (Pydantic models)
- [x] docs/decisions.md (ADR-001 stack choice)
- [x] .github/workflows/ci.yml skeleton
- [ ] `gh repo create` → push to GitHub
- [ ] CI green on main

**Done when:** Repo on GitHub, CI runs.

---

## Phase 1 — Clients, tools, MCP server
- [ ] `src/companylens/clients/ratelimit.py` — token-bucket
- [ ] `src/companylens/clients/cache.py` — in-memory + disk TTL
- [ ] `src/companylens/clients/companies_house.py`
- [ ] `src/companylens/clients/fca.py`
- [ ] `src/companylens/clients/news.py`
- [ ] `src/companylens/tools/registry.py`
- [ ] `src/companylens/tools/company_tools.py`
- [ ] `scripts/record_fixtures.py`
- [ ] `tests/fixtures/` — 8 companies, scrubbed
- [ ] `src/companylens/mcp_server/server.py`
- [ ] `docs/mcp.md`
- [ ] Tests: each client, rate limiter, cache, every tool, MCP list+call

**Done when:** All tools tested offline; MCP list/call test passes.

---

## Phase 2 — LangGraph agent
- [ ] `src/companylens/agent/state.py`
- [ ] `src/companylens/agent/graph.py` (resolve → plan → act → decide → report)
- [ ] `src/companylens/agent/guards.py`
- [ ] `src/companylens/agent/risk.py`
- [ ] `src/companylens/agent/prompts/v1/` (system + report prompts)
- [ ] `src/companylens/llm.py`
- [ ] `src/companylens/config.py` (named configs)
- [ ] `src/companylens/observability.py`
- [ ] First Docker image + memory check under 512 MB

**Done when:** 5 live dev companies produce valid reports; memory recorded in eval/results/memory.json.

---

## Phase 3 — Claim check, baseline, safety
- [ ] `src/companylens/agent/claim_check.py`
- [ ] `src/companylens/agent/baseline.py`
- [ ] Human approval (interrupt/checkpoint) wired to API
- [ ] Prompt-injection defences
- [ ] Named configs in config.py
- [ ] Fake-LLM graph tests for all paths

**Done when:** Fake-LLM graph tests pass for all paths.

---

## Phase 4 — FastAPI + UI + Langfuse
- [ ] `src/companylens/api/main.py`
- [ ] `src/companylens/api/ratelimit.py`
- [ ] `src/companylens/api/budget.py`
- [ ] `src/companylens/api/static/index.html`
- [ ] SSE streaming (/report/stream)
- [ ] Playwright checks (desktop + phone)
- [ ] Langfuse OTLP integration

**Done when:** UI works on desktop and phone; traces visible in Langfuse.

---

## Phase 5 — Eval infrastructure
- [ ] `eval/companies/` — selection script, dev.jsonl, test.jsonl (~80 companies)
- [ ] `eval/snapshot.py`
- [ ] `eval/ground_truth/` — derived facts, no personal data
- [ ] `eval/metrics.py`
- [ ] `eval/judge.py`
- [ ] `eval/bootstrap.py`
- [ ] Dev eval runs end to end

**Done when:** Dev eval runs end to end.

---

## Phase 6 — Experiments
- [ ] E1 agent vs baseline
- [ ] E2 model comparison
- [ ] E3 claim-check ablation
- [ ] E4 guard stress test
- [ ] E5 prompt-injection test
- [ ] `eval/results/summary.md` + charts
- [ ] `docs/failure_analysis.md` (8+ real cases)
- [ ] `eval/hand_check.csv`

**Done when:** summary.md + charts + 8 failure cases.

---

## Phase 7 — Deploy
- [ ] Final Docker memory check < 350 MiB
- [ ] `render.yaml`
- [ ] Live Playwright check (3 reports + 1 refusal)
- [ ] Confirm Langfuse traces
- [ ] Cold-start measurement

**Done when:** Live site works, no OOM, 429 works.

---

## Phase 8 — README, GIF, interview notes
- [ ] README (spec §12)
- [ ] Demo GIF (Playwright → GIF, < 5 MB)
- [ ] Screenshots
- [ ] Repo metadata (description, website, topics)
- [ ] `private/interview_notes.md`
- [ ] Final independent review (fresh sub-agent)
- [ ] All items in §14 definition of done checked

**Done when:** §14 checklist all true.

---

## Decisions log
See `docs/decisions.md` for full ADRs.

| ID | Decision | Status |
|----|----------|--------|
| ADR-001 | Tech stack | Accepted |

## Blockers
_None currently._
