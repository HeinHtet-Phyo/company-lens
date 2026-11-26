# CLAUDE.md — CompanyLens agent rules

## This project
CompanyLens is an AI agent for UK company due-diligence. It queries Companies House, the FCA Register and GDELT, then returns a structured, evidence-cited report.

## Critical rules

### Security
- **Never print, log, echo or commit key values.** Keys live in `.env` only.
- Before every commit: `git diff --cached | grep -iE "key|secret|token"` and check no real values appear.
- `.gitignore` must cover `.env`, `.venv/`, `__pycache__/`, `*.pyc`, `private/`, `data/raw/`, `.pytest_cache/`.

### Data protection
- Officer and PSC names may appear in reports (they're on the public register), but **never** DOBs, residential addresses, service addresses, nationality, or other personal details.
- Logs and Langfuse traces must redact officer/PSC names (replace with role+index), emails and phone numbers.
- Fixtures must have personal data scrubbed before commit.
- Never let users search for people; refuse person-centred requests.

### Memory and performance
- Use the **official `openai` Python SDK** pointed at OpenAI-compatible endpoints. No LiteLLM or LangChain model wrappers at runtime.
- Peak memory target: **under 350 MiB** measured with `docker run --memory=512m`.
- Set `OMP_NUM_THREADS=1`; run uvicorn with `--workers 1`.

### Error handling
- The API must never return an empty 500. Catch exceptions → log → return JSON error with exception class.
- UI must handle 429, 503 (budget), 502/504 (gateway) with clear messages.

### Rate limits
- Read client IP from first `X-Forwarded-For` entry.
- Companies House: client-side token-bucket under 600 req/5 min.

### Code quality
- `mypy --strict` clean, `ruff format` + `ruff lint` clean.
- Docstrings on all public functions.
- `make test` must pass with no network and no keys (fixtures only).

### Commits
- Conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `eval:`.
- Small commits, push after each phase.
- Keep `PLAN.md` updated with status, decisions and spend.

### Never claim work done without evidence
- Show test counts, commit hashes, or file paths as proof.
- Run `make test` and show output before marking a phase done.

## Budget
- Nebius: under **$15** total. Track in `eval/results/spend.json`.
- Mistral: free credits only. If billing is required, stop and report.
- API rate limit: 10 reports/min/IP; daily cap £0.50 (env `DAILY_BUDGET_GBP`).

## When to stop and ask Hein
1. `pwd` is not the company-lens folder.
2. `COMPANIES_HOUSE_API_KEY` or `NEBIUS_API_KEY` is empty when live calls are needed.
3. `gh` isn't authenticated.
4. Spend would exceed budget, or Mistral asks for billing.
5. Render service or env vars need to be created (Hein does this).
6. Anything that would delete files outside the project or rewrite git history.
