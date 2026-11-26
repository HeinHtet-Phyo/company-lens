# CompanyLens — Build Plan

**Last updated:** 2026-11-26  
**Spend so far:** ~£0.64 est. (see eval/results/spend.json)  
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

## Status (updated 2026-11-26) — READ THIS FIRST AFTER ANY COMPACTION

Also re-read CLAUDE.md. Hein's standing instruction: keep building without stopping except at CLAUDE.md blockers; never print key values.

### Phases
- Phase 0 scaffold: done. Phase 1 clients/tools/MCP: done (fixtures: `scripts/record_fixtures.py` → `tests/fixtures/companies.json`, 8 companies, aggregate data only).
- Phase 2 agent (LangGraph), guards, risk R1–R9, Docker: done. Phase 3: claim check + baseline + injection defence done; **human-approval interrupt NOT implemented** (state fields exist, unused) — say so in README/interview notes unless built.
- Phase 4 API + SSE + static UI: done, Playwright-checked at 1440px and iPhone 13 (docs/screenshots/). 429/503/refusal UI paths not browser-tested.
- Phase 5–6 eval: harness built (eval/: build_set, snapshot, run_eval, judge [gemma-3-27b-it], metrics, analyze, run_e5, make_hand_check, refresh_fca). Dev run done for 5 configs. **Test split run once in background (see below).**
- Phase 7 (Render deploy review, live checks) and Phase 8 (README, GIF, docs, interview notes, final review, secret/PII scan, repo metadata): NOT started.

### Measured so far (files are the source of truth)
- Memory (eval/results/memory.json): peak 92.2 MiB under --memory=512m, idle 84.1, no OOM, image 433 MB, cold start 1.4 s.
- Tests: 154 passed, 1 skipped (+1 flaky error seen once in tests/unit/test_clients.py::test_search_companies_returns_candidates when run in the full suite — passed alone; investigate).
- Dev split (n=26, eval/results/metrics_dev_*.json): agent_qwen routing 100%, risk agreement 100%, flag recall 93%, ~£0.008/report, 16 s; baseline_fixed routing 77% (naive resolver fails ambiguous/nonexistent), recall 100%, ~£0.0003/report, 7 s. agent_small cheaper (£0.001) but recall 82%. Claim check cut reports-with-unsupported-sentence 35% → 24% (wide CIs). Do not quote these in README until test numbers exist; README uses TEST numbers.
- Spend (eval/results/spend.json, estimated not invoiced): £0.64 so far incl. dev + part of test; cap in run_eval.py is £8 est.; Nebius budget $15.

### Background job (started before this update)
`run_eval.py --split test --configs baseline_fixed,agent_qwen,agent_small,agent_qwen_noclaimcheck,agent_qwen_tight` then `score.py --split test ...` then `run_e5.py`. Check: `ls eval/results/runs/` (test_*.jsonl appear per config; baseline_fixed and agent_qwen were done), `pgrep -fl run_eval`, then `ls eval/results/metrics_test_*.json eval/results/e5.json`. Test files are WRITE-ONCE: never delete/re-run test_*.jsonl; if the job died, run only the missing configs. If score.py did not run: `PYTHONPATH=eval .venv/bin/python eval/score.py --split test --configs ...` (re-scoring is allowed; judge results cached in eval/results/judge_cache.json). Then `PYTHONPATH=eval .venv/bin/python eval/analyze.py` for summary.md + charts.
Note: the running job loaded code from before the FCA-limitation-wording change (wording only).

### Credentials (Hein added; values never printed)
- Langfuse: OTLP export works (v3 ingestion was removed 2026-11-16 → HTTP 410; tracer rewritten); verified by `scripts/verify_langfuse.py` (trace read back, 4 observations).
- Mistral: one tool-call test OK on `mistral-small-latest`, no billing prompt. Dev run of agent_mistral NOT yet done (free tier: use low concurrency; if billing is demanded, STOP and tell Hein).
- FCA: portal down, no key. Decision (Hein): keep "credentials not configured", shown in report limitations (done) and README (TODO); FCA excluded from eval metrics (documented in docs/eval_method.md); re-run later with `python eval/refresh_fca.py`. FCA `/Firm/Search` endpoint unverified.

### Open items (in order)
1. Finish/verify test run, score, analyze (charts → eval/results/charts), E5 results.
2. agent_mistral dev run (low concurrency) + test run once if it works; add to EXPERIMENTS in analyze.py as E-Mistral.
3. docs/failure_analysis.md (≥8 real cases from runs; include number-check false positives, Cambridge Analytica shell-company name collision, naive baseline resolution, round-limit stops).
4. eval/hand_check.csv via `eval/make_hand_check.py` (human columns left blank; judge-vs-human agreement therefore unmeasured — say so).
5. Fix flaky test_clients error; confirm `make test` green; ruff/mypy clean.
6. Phase 7: render.yaml review; tell Hein exact env var names for Render (COMPANIES_HOUSE_API_KEY, NEBIUS_API_KEY, MISTRAL_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST, DAILY_BUDGET_GBP; FCA_* later); Hein creates the service (blocker per CLAUDE.md #5); then live Playwright, 429/OOM checks, cold start.
7. Phase 8: README (FCA note, honest numbers from eval/results only), demo GIF, docs/architecture.md (safety.md, data_and_privacy.md, eval_method.md already written), private/interview_notes.md, repo description/topics, fresh-agent independent review, secret + personal-data scan of history.
8. Optional: human-approval interrupt.
