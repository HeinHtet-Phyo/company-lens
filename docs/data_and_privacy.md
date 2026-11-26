# Data and privacy

**Sources:** Companies House public API, FCA Register API (credentials required; see below), GDELT DOC API (news).

**What the tools return.** Company-level facts only. Officer data is reduced to counts (active directors, secretaries, resignations in 12 months). PSC data is reduced to counts, kinds and the names of *corporate* PSCs. Individuals' names, dates of birth, nationality, residential and service addresses are never returned to the model, so they cannot appear in a report.

**Logs and traces.** `observability.redact` replaces officer/PSC names (role + index), emails and phone numbers before anything is sent to Langfuse or logged. Query text is not stored in traces beyond its length.

**Eval data.** `eval/snapshots/snapshot.json` holds frozen tool outputs. Because tool outputs are already aggregate, it contains no personal data. Refusal test prompts contain fictional person names only.

**Keys.** Only in `.env` (git-ignored). Nothing prints key values.

**Not covered:** the FCA Register check is implemented but could not be verified against the live FCA API (no credentials during the build), so in every evaluation run it reported "credentials not configured" and rule R8 never fired.
