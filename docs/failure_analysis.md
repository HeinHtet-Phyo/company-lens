# Failure analysis

Real failures from the dev and test runs (`eval/results/runs/*.jsonl`, scored in `eval/results/metrics_*.json`). IDs refer to `eval/companies/set.json`. Cases 1–6 are from the test split and are **not** fixed, because the test split was run once and is not tuned against. Cases 7–10 were found on dev and fixed before the test run.

## Open failures (test split)

### 1. Ambiguous names resolved to a single company (c052 Apple, c053 Acme, c055 London Consulting, c058 Greenfield Properties, c059 Alpha Solutions, c060 Royal Bakery)
`agent_qwen` returned a report instead of asking which company was meant, e.g. APPLE LTD (dissolved, flagged R3 High), ACME LTD, LONDON CONSULTING LTD. These six ambiguous items plus case 1b below are all 7 of the agent's routing failures on test (87% = 47/54). `baseline_fixed` also failed these, and c057 Phoenix.
**Cause:** the resolver auto-picks a unique exact name match (after removing the legal suffix). The first search page held only one such match, so the rule saw no ambiguity even though many companies share these names on the register.
**Consequence:** a confident, cited report about the wrong company. This is the most serious open failure.
**Possible fix (implemented as resolver v2, commit be9c4c9):** ask whenever a bare name (no legal-form word typed) has two or more active prefix matches, even with one exact hit. Validated on dev (routing 100% before and after) and on a fresh 15-name set (routing 67% to 100%, ambiguous 0% to 100%). The test split was NOT re-run, so these six test failures are still recorded as open for the test numbers. Live check: "Acme" and "Monzo Bank" now return choice buttons.

### 1b. Nonexistent name still produced a report (c068 "Wxyzabc Foobarbaz Ltd")
The overlap guard that fixed the dev cases (case 8) did not stop this one; the agent returned a report instead of not-found. Not investigated further.

### 2. Large plcs: insolvency and charges checks skipped, flags missed (c021 Ocado, c037 ASOS, c039 Sainsbury's)
Reports stopped as `complete` with limitations "Check not performed: get_insolvency" and "get_charges", so the risk level was Low and the oracle (computed from all tools in the snapshot) disagreed (`risk_ok` false). c023 Debenhams missed one flag the same way.
**Cause:** the model decided it had enough evidence and the decide step accepted it. The report honestly says the checks were not run, but the risk level is still presented as Low.
**Possible fix:** make profile, officers, PSC, charges and insolvency mandatory before risk is computed, or cap the risk level as "incomplete" when a rule input is missing.

### 3. Run stopped by the LLM round limit (c040 NF001705, c042 16351760)
Both company-number queries hit `llm_round_limit`. Reports were still produced from partial evidence and say so under limitations. c040 had flags R3 and R4 but no insolvency check.
**Cause:** the agent tried `search_companies` for a number (not in the snapshot) and spent rounds retrying instead of going straight to the profile.

### 4. Replay gaps: "not in snapshot" (c052, c053, c055)
When the agent picked a company the snapshot builder had not recorded, the evaluation returned "not in snapshot" for officers, filings and PSC. That is an evaluation artefact: those runs show a Low risk and thin evidence partly because the data was never recorded, not because the agent skipped it.
**Impact:** per-item risk and recall scores on wrongly resolved items are not meaningful. They are excluded from risk scoring by design (risk_ok is None).

### 5. Tight tool budget collapses recall (E4, `agent_qwen_tight`)
Capping at 3 tool calls: flag recall 65% vs 92%, risk agreement 74% vs 91%, 71% of reports contain at least one judge-flagged unsupported sentence vs 31%, and 0% finish without a guard. Cost fell from about £0.007 to £0.002 per report. The agent spends its three calls on the profile and searches and never reaches charges or insolvency. This is a measured trade-off, not a bug.

### 6. Unsupported sentences remain after the claim check (all configs)
About 31% of `agent_qwen` test reports still contain at least one sentence the judge calls unsupported (7% of sentences); the claim check lowers this only slightly on the test split (31% vs 33% without it; intervals overlap heavily). The deterministic number check flags 9% of numbers. For example c003, c004, c013 and c016 each have one number in the summary that does not appear in the evidence or facts. I have not adjudicated each by hand; `eval/hand_check.csv` exists for that, and judge-vs-human agreement is unmeasured until it is filled in.

## Fixed during development (dev split)

### 7. Resolver skipped a company in administration (NMC Health)
Searching by name returned several exact matches and the status filter dropped the one that was in administration. Fixed: a unique exact match is accepted regardless of status, and non-dissolved matches are only preferred when several exist.

### 8. Junk match for nonexistent names (NNNN LIMITED, FOOBARBAZ LTD)
The search API returned loosely similar companies and the model accepted one. Fixed with a token-overlap guard (at least 0.5 overlap with the query) before the model's verdict. Dev routing for the nonexistent category went from failing to 100%; the baseline, which takes the top hit, still scores 0% there on dev.

### 9. Number check false positives
The first number check flagged dates ("12 March 2019") and number words ("ten directors") as unsupported. Fixed by normalising dates and number words on both sides. The dev unsupported-number rate is still noisy because of the small sample.

### 10. Name collision with shell companies (Cambridge Analytica)
A search for a well-known failed firm returned several companies with near-identical names, including shell entities. This case motivated the clarification path and the rule to reject a candidate list instead of guessing when more than one live match remains. The ambiguity in case 1 shows the rule is incomplete.

## Found during live deployment
- **Static UI and prompts missing from the Docker image.** `pip install .` did not include `index.html` or the prompt `.txt` files, so the first live deploy returned a 500 on `/` and reports would have failed. Local runs used the source tree and the earlier memory test only called `/health`. Fixed with `package-data` in pyproject.toml (e5f48a7) and a test that the patterns cover those files.
- **Langfuse 401 from the live service.** Keys set in Render are rejected by Langfuse (`/health` shows `last_status` 401) while the same host works with local keys. Needs the Render env vars re-entered.
- **Insolvency/charges skipped on Rightmove plc (live).** Same behaviour as case 2: Low risk with two checks not performed.

## Data-source limitation
GDELT rate-limited the snapshot builder (429s and timeouts); only 24 of 76 snapshot entries have news. Reports then carry "search_news unavailable" under limitations. FCA data is absent for all runs (credentials not configured) and is excluded from all metrics.

## Evaluation bug found in review
The first E5 run reported 30/30 resisted, but the payload was written to a profile field that does not exist, the tool call errored, and every run ended `not_found` with no report. The harness now injects into `registered_office_locality`, counts no-report runs as invalid, and the re-run gave 29/30 (1 flag-set change on c040, cause not determined).
