"""Tests for eval helpers (pure functions; no network)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "eval"))

from judge import sentences
from metrics import boot_ci, unsupported_numbers
from snapshot import key


def test_snapshot_key_ignores_limit_and_case() -> None:
    assert key("search_companies", {"query": "Acme ", "limit": 5}) == key(
        "search_companies", {"query": "acme"}
    )


def test_sentences_splits_and_drops_fragments() -> None:
    out = sentences("Acme is active [e1]. It has two directors [e2]. Ok.")
    assert len(out) == 2


def test_boot_ci_brackets_mean_and_is_deterministic() -> None:
    xs = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    m, lo, hi = boot_ci(xs)
    assert lo <= m <= hi and boot_ci(xs) == (m, lo, hi)


def test_unsupported_numbers() -> None:
    rep = {
        "summary": "It has 13 directors and 99 charges [e1].",
        "evidence": [{"excerpt": "directors: 13"}],
        "facts": [],
    }
    assert unsupported_numbers(rep) == (1, 2)
