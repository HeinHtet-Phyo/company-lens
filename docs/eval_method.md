# Evaluation method

## Set
80 inputs in `eval/companies/set.json` (built by `eval/build_set.py`, seed 20260101): 40 company names (each pinned to the one exact-name match Companies House returns), 12 company numbers, 10 ambiguous names, 8 non-existent names, 10 must-refuse prompts. Split is stratified per category: **dev** (26) for tuning and **test** (54), which is run **once** per config (`run_eval.py` refuses to overwrite a test result file). A further 5 injection payloads × 6 companies form the E5 stress test (`run_e5.py`); these are fixed and were not tuned.

The company-name labels are hand-chosen and some are subjective (e.g. whether "Greenfield Properties" is ambiguous). The unique-name labels come from Companies House exact-name matching and drop any name with more than one live exact match.

## Frozen data
All configs run against `eval/snapshots/snapshot.json`, tool outputs recorded once from the live APIs. That makes configs comparable and the eval repeatable offline. A tool call that is not in the snapshot returns "not in snapshot" (misses are counted in the run output). **GDELT news mostly failed during recording** (rate limits/timeouts), so most snapshot entries for `search_news` are failures; news is effectively a minor input in this eval.

## Ground truth and what it can and cannot show
- **Routing**: right company number / clarification for ambiguous / not_found for non-existent / refusal.
- **Risk level and flags**: oracle = the deterministic rules (R1–R9) applied to the full snapshot for the pinned company. The baseline calls every tool, so it matches the oracle by construction; the question for E1 is what the adaptive agent loses (recall) and gains (cost/latency) by choosing tools. This is not an independent label of "true risk".
- **Faithfulness**: a judge from a different model family (`google/gemma-3-27b-it`) checks each summary sentence against the report's evidence excerpts. Plus a deterministic check that numbers in the summary appear in the evidence (number words and dates are normalised). Both are noisy; `eval/hand_check.csv` holds 20 sentences for a human to verify, and the judge's agreement with the human labels is **not yet measured** until those columns are filled.
- Cost is estimated from token counts and a price table (`llm.py`), not invoices.
- Intervals are 95% bootstrap CIs over items (2000 resamples). With 15–54 items they are wide; differences inside the intervals should not be read as effects.

## FCA is excluded
The FCA developer portal was down, so there is no FCA key. Every run reported "FCA credentials not configured", rule R8 never fired, and **FCA fields are excluded from all metrics** (the oracle passes `fca=None`). To add it later: put `FCA_API_EMAIL`/`FCA_API_KEY` in `.env`, run `python eval/refresh_fca.py` (re-records only the FCA snapshot entries for financial-SIC companies), then re-run the affected items as a new, clearly labelled experiment. The `/Firm/Search` endpoint in `clients/fca.py` has never been verified against the live API.

## Experiments
- E1 agent vs fixed pipeline (same models for summary/judge; only tool selection differs; the baseline resolves names naively = top search hit).
- E2 model size: Qwen3.8-27B vs Qwen3-30B-A3B as the tool-calling model.
- E3 claim check on vs off.
- E4 tight budget (3 tool calls / 4 LLM rounds) vs default.
- E5 prompt injection.
- Mistral (`agent_mistral`) is an additional config where its free tier allows; see summary.
