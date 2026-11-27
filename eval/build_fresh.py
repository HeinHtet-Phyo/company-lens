"""Build eval/companies/fresh.jsonl: 15 names never used in set.json (5 clear, 5 ambiguous, 5 not-found).

Live run, once. Pools are fixed in code; sampling uses a fixed seed. Candidates are verified against
Companies House (clear: one live exact match; ambiguous: >=2 live companies share the name prefix;
not-found: no candidate shares a word with the query).
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

from companylens.agent.graph import _norm_name, _overlap
from companylens.clients.companies_house import CompaniesHouseClient

SEED = 1127
OUT = Path(__file__).parent / "companies" / "fresh.jsonl"
SET = Path(__file__).parent / "companies" / "set.json"

CLEAR = [
    "RIGHTMOVE PLC", "HALMA PLC", "SPIRAX GROUP PLC", "CRODA INTERNATIONAL PLC",
    "DUNELM GROUP PLC", "SMITHS GROUP PLC", "BUNZL PLC", "GAMES WORKSHOP GROUP PLC",
]  # fmt: skip
AMBIGUOUS = [
    "Sterling", "Pioneer Holdings", "Horizon Trading", "Summit Partners",
    "Orchard Services", "Falcon Logistics", "Evergreen Consulting", "Beacon Ventures",
    "Atlas Developments", "Crown Consulting", "Imperial Trading", "Northern Services",
]  # fmt: skip
NOT_FOUND = [
    "Qvxtrl Plonbwe Ltd", "Zzmrkt Hjdquo Limited", "Yfglop Ruwqen Ltd", "Blorptz Quangle Ltd",
    "Xkcdwy Merblat Limited", "Fnorgle Wuxtab Co", "Prwzzk Olmnet Partners", "Dvqqx Lrmpt Group",
    "Gwrbl Tnxqz Ltd", "Hvkpq Sdorm Limited", "Wzqrtn Ploxvu Ltd", "Jkxvw Pnrlq Limited",
]  # fmt: skip


async def main() -> None:
    used = {i["query"].lower() for i in json.loads(SET.read_text())["items"]}
    rng = random.Random(SEED)
    items: list[dict[str, object]] = []
    async with CompaniesHouseClient() as ch:
        for cat, pool in (
            ("unique_name", CLEAR),
            ("ambiguous", AMBIGUOUS),
            ("nonexistent", NOT_FOUND),
        ):
            pool = [p for p in pool if p.lower() not in used]
            rng.shuffle(pool)
            kept: list[dict[str, object]] = []
            for q in pool:
                if len(kept) == 5:
                    break
                cands = ((await ch.search_companies(q, limit=5)).data or {}).get("candidates", [])
                nq = _norm_name(q)
                if cat == "unique_name":
                    live = [
                        c
                        for c in cands
                        if _norm_name(c["name"]) == nq and c["status"] != "dissolved"
                    ]
                    ok = len(live) == 1
                    extra = {"expected_number": live[0]["number"]} if ok else {}
                elif cat == "ambiguous":
                    ok = (
                        sum(
                            _norm_name(c["name"]).startswith(nq) and c["status"] != "dissolved"
                            for c in cands
                        )
                        >= 2
                    )
                    extra = {"expected_type": "clarification"}
                else:
                    ok = not any(_overlap(nq, _norm_name(c["name"])) > 0 for c in cands)
                    extra = {"expected_type": "not_found"}
                if ok:
                    kept.append({"category": cat, "query": q, **extra})
                else:
                    print("dropped:", cat, q)
            items += kept
    for n, it in enumerate(items):
        it["split"] = "fresh"
        it["id"] = f"f{n:03d}"
    OUT.write_text("\n".join(json.dumps(i) for i in items) + "\n")
    print(len(items), "items written")


if __name__ == "__main__":
    asyncio.run(main())
