"""Input validation: length limits and refusal of person-centred or injection requests."""

from __future__ import annotations

import re

_REFUSE = [
    r"\b(home|residential|personal|private)\s+address\b",
    r"\bdate of birth\b|\bdob\b|\bborn on\b",
    r"\b(phone|mobile|telephone)\s+(number|no)\b|\bemail address\b",
    r"\bcriminal\b|\bconvicted\b|\bmugshot\b|\bcriminal record\b",
    r"\bnational insurance\b|\bpassport\b",
    r"\bignore (all |your |any )?(previous |prior |above )?(rules|instructions|prompt)",
    r"\bsystem prompt\b|\bdisregard\b.*\b(rules|instructions)\b|\bjailbreak\b",
]
_REFUSE_RE = [re.compile(p, re.IGNORECASE) for p in _REFUSE]
_PERSON_RE = re.compile(r"\b(is|where does|who is|find|about)\s+(mr|mrs|ms|dr)\.?\s+\w+", re.I)

REFUSAL_MESSAGE = (
    "CompanyLens covers UK companies only. It can't look up private individuals, "
    "personal details, or follow instructions that change its rules."
)


def check_input(query: str) -> tuple[bool, str | None]:
    """Return (ok, message). ok=False means refuse or reject with ``message``."""
    q = query.strip()
    if not 2 <= len(q) <= 120:
        return False, "Query must be between 2 and 120 characters."
    if any(r.search(q) for r in _REFUSE_RE) or _PERSON_RE.search(q):
        return False, REFUSAL_MESSAGE
    return True, None
