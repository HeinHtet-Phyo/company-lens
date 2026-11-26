"""Deterministic + LLM-assisted claim verification for CompanyLens reports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from companylens.models import Evidence, Fact, Report

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ClaimCheckResult:
    passed: bool  # overall pass/fail
    checked_facts: int
    failed_facts: list[str] = field(default_factory=list)  # field names that failed
    checked_sentences: int = 0
    failed_sentences: list[str] = field(default_factory=list)  # unsupported sentences
    path_taken: str = "passed"  # "passed" | "repaired" | "dropped"
    limitations_added: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic fact check
# ---------------------------------------------------------------------------


def _evidence_by_id(evidence: list[Evidence]) -> dict[str, Evidence]:
    return {ev.id: ev for ev in evidence}


def _value_in_excerpt(value: str, excerpt: str) -> bool:
    """Return True if *value* appears as a substring (case-insensitive) in *excerpt*."""
    return value.lower() in excerpt.lower()


def _date_partial_match(value: str, excerpt: str) -> bool:
    """Allow year-month match for dates: 'YYYY-MM' anywhere in excerpt."""
    # Extract YYYY-MM prefix from value like "2023-05-01" or "2023-05"
    m = re.match(r"(\d{4}-\d{2})", value)
    if m:
        return m.group(1) in excerpt
    return False


def check_facts_against_evidence(
    facts: list[Fact],
    evidence: list[Evidence],
) -> tuple[bool, list[str]]:
    """Exact-match check for each Fact.

    For each Fact, verify its value appears in the excerpts of the cited
    evidence items.  Returns ``(all_passed, failed_field_names)``.

    - Booleans and numbers: convert to string and check substring.
    - Dates: allow partial match (year-month is enough).
    """
    ev_map = _evidence_by_id(evidence)
    failed: list[str] = []

    for fact in facts:
        # Gather excerpts from cited evidence
        cited_excerpts: list[str] = []
        for ev_id in fact.evidence_ids:
            ev = ev_map.get(ev_id)
            if ev:
                cited_excerpts.append(ev.excerpt)

        if not cited_excerpts:
            # No evidence to verify against - mark as failed
            failed.append(fact.field)
            continue

        combined = " ".join(cited_excerpts)
        value = fact.value

        found = _value_in_excerpt(value, combined) or _date_partial_match(value, combined)

        if not found:
            failed.append(fact.field)

    all_passed = len(failed) == 0
    return all_passed, failed


# ---------------------------------------------------------------------------
# LLM sentence-level check
# ---------------------------------------------------------------------------

_SENTENCE_CHECK_SYSTEM = (
    "You are a fact-checking assistant. "
    "You will be given a summary sentence and evidence excerpts. "
    "Determine whether the sentence is supported by the evidence. "
    "Respond with a JSON array. Each element has: "
    '{"sentence": "<sentence>", "verdict": "supported"|"unsupported"|"not_a_claim"}. '
    "Only mark as 'not_a_claim' if the sentence is a boilerplate disclaimer or contains no factual claim."
)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (simple heuristic)."""
    # Split on ". ", "! ", "? " followed by an uppercase letter
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [s.strip() for s in raw if s.strip()]


async def check_summary_against_evidence(
    summary: str,
    evidence: list[Evidence],
    llm_client: Any,  # openai.AsyncOpenAI compatible client
    model: str,
) -> tuple[list[str], list[str]]:
    """Split summary into sentences.

    For each sentence, ask the LLM: is this sentence supported by the evidence?
    Returns ``(supported_sentences, unsupported_sentences)``.

    Uses structured output: JSON list of
    ``{"sentence": ..., "verdict": "supported"|"unsupported"|"not_a_claim"}``.
    """
    sentences = _split_sentences(summary)
    if not sentences:
        return [], []

    evidence_text = "\n\n".join(f"[{ev.id}] ({ev.tool}) {ev.excerpt}" for ev in evidence)

    sentences_block = "\n".join(f"- {s}" for s in sentences)

    user_content = (
        f"Evidence:\n{evidence_text}\n\n"
        f"Sentences to check:\n{sentences_block}\n\n"
        "Return a JSON array with one object per sentence."
    )

    response = await llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SENTENCE_CHECK_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    raw_content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw_content)
        # The model may wrap the array in a key
        if isinstance(parsed, dict):
            # Try common wrapper keys
            for key in ("results", "sentences", "items", "verdicts"):
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break
            else:
                # Fall back to first list value
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        break
                else:
                    parsed = []
    except json.JSONDecodeError:
        parsed = []

    supported: list[str] = []
    unsupported: list[str] = []

    verdict_map: dict[str, str] = {}
    for item in parsed:
        if isinstance(item, dict):
            sent = str(item.get("sentence", ""))
            verdict = str(item.get("verdict", "unsupported")).lower()
            verdict_map[sent] = verdict

    for sentence in sentences:
        verdict = verdict_map.get(sentence, "unsupported")
        if verdict in ("supported", "not_a_claim"):
            supported.append(sentence)
        else:
            unsupported.append(sentence)

    return supported, unsupported


# ---------------------------------------------------------------------------
# Full claim-check pipeline
# ---------------------------------------------------------------------------

_REPAIR_SYSTEM = (
    "You are a report editor. "
    "You will be given a summary and a list of sentences that are NOT supported by evidence. "
    "Rewrite the summary removing or softening unsupported claims. "
    "Preserve factual, supported content. Return only the revised summary text."
)


async def run_claim_check(
    report: Report,
    llm_client: Any,
    model: str,
) -> tuple[Report, ClaimCheckResult]:
    """Run the full claim-check pipeline.

    1. check_facts_against_evidence
    2. check_summary_against_evidence
    3. If summary has unsupported sentences: regenerate once with feedback
    4. If still unsupported after regeneration: drop those sentences, add to limitations
    5. Return updated report and result
    """
    # Step 1 - fact check
    facts_passed, failed_facts = check_facts_against_evidence(report.facts, report.evidence)
    checked_facts = len(report.facts)

    # Step 2 - sentence check
    supported_sents, unsupported_sents = await check_summary_against_evidence(
        report.summary, report.evidence, llm_client, model
    )
    checked_sentences = len(supported_sents) + len(unsupported_sents)

    limitations_added: list[str] = []
    path_taken = "passed"

    if unsupported_sents:
        # Step 3 - attempt one repair
        path_taken = "repaired"
        repair_prompt = (
            f"Original summary:\n{report.summary}\n\n"
            f"Unsupported sentences to remove or soften:\n"
            + "\n".join(f"- {s}" for s in unsupported_sents)
        )
        repair_response = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _REPAIR_SYSTEM},
                {"role": "user", "content": repair_prompt},
            ],
            temperature=0,
        )
        repaired_summary: str = (repair_response.choices[0].message.content or "").strip()

        # Step 4 - check the repaired summary
        _, still_unsupported = await check_summary_against_evidence(
            repaired_summary, report.evidence, llm_client, model
        )

        if still_unsupported:
            # Drop remaining unsupported sentences
            path_taken = "dropped"
            all_sents = _split_sentences(repaired_summary)
            kept = [s for s in all_sents if s not in still_unsupported]
            final_summary = " ".join(kept) if kept else repaired_summary
            limitations_added = [
                f"The following claims could not be verified and were removed: {s}"
                for s in still_unsupported
            ]
        else:
            final_summary = repaired_summary
            still_unsupported = []

        # Rebuild report with updated summary and limitations
        updated_limitations = list(report.limitations) + limitations_added
        updated_report = report.model_copy(
            update={"summary": final_summary, "limitations": updated_limitations}
        )
    else:
        updated_report = report
        still_unsupported = []

    overall_passed = facts_passed and len(still_unsupported) == 0

    result = ClaimCheckResult(
        passed=overall_passed,
        checked_facts=checked_facts,
        failed_facts=failed_facts,
        checked_sentences=checked_sentences,
        failed_sentences=still_unsupported if unsupported_sents else unsupported_sents,
        path_taken=path_taken,
        limitations_added=limitations_added,
    )

    return updated_report, result
