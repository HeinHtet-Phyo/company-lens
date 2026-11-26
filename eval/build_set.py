"""Resolve candidates against Companies House and build eval/companies/set.json (live; run once)."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

from candidates import AMBIGUOUS_QUERIES, NONEXISTENT_QUERIES, REFUSE_QUERIES, UNIQUE_CANDIDATES

from companylens.agent.graph import _norm_name
from companylens.clients.companies_house import CompaniesHouseClient

SEED = 20260101
OUT = Path(__file__).parent / "companies" / "set.json"


def norm(s: str) -> str:
    return "".join(c for c in s.upper() if c.isalnum())


async def main() -> None:
    resolved: list[dict[str, str]] = []
    async with CompaniesHouseClient() as ch:
        for name in UNIQUE_CANDIDATES:
            r = await ch.search_companies(name, limit=5)
            cands = (r.data or {}).get("candidates", [])
            exact = [c for c in cands if _norm_name(c["name"]) == _norm_name(name)]
            live = [c for c in exact if c["status"] != "dissolved"]
            pool = live or exact
            hit = pool[0] if len(pool) == 1 else None
            if hit:
                resolved.append({"name": hit["name"], "number": hit["number"]})
            else:
                print("dropped (no unique exact match):", name, [c["name"] for c in cands[:3]])
    rng = random.Random(SEED)
    rng.shuffle(resolved)
    n_num = min(12, len(resolved) // 4)
    by_number, by_name = resolved[:n_num], resolved[n_num:][:40]
    items: list[dict[str, object]] = []
    for c in by_name:
        items.append(
            {"category": "unique_name", "query": c["name"], "expected_number": c["number"]}
        )
    for c in by_number:
        items.append({"category": "number", "query": c["number"], "expected_number": c["number"]})
    for q in AMBIGUOUS_QUERIES:
        items.append({"category": "ambiguous", "query": q, "expected_type": "clarification"})
    for q in NONEXISTENT_QUERIES:
        items.append({"category": "nonexistent", "query": q, "expected_type": "not_found"})
    for q in REFUSE_QUERIES:
        items.append({"category": "refuse", "query": q, "expected_type": "refused"})
    # stratified dev/test split: ~1/3 dev per category
    by_cat: dict[str, list[dict[str, object]]] = {}
    for it in items:
        by_cat.setdefault(str(it["category"]), []).append(it)
    for cat_items in by_cat.values():
        rng.shuffle(cat_items)
        k = max(1, round(len(cat_items) / 3))
        for i, it in enumerate(cat_items):
            it["split"] = "dev" if i < k else "test"
    for i, it in enumerate(items):
        it["id"] = f"c{i:03d}"
    OUT.write_text(json.dumps({"seed": SEED, "items": items}, indent=1))
    print(
        len(items),
        {c: len(v) for c, v in by_cat.items()},
        "dev",
        sum(i["split"] == "dev" for i in items),
    )


if __name__ == "__main__":
    asyncio.run(main())
