"""Write eval/hand_check.csv: 20 sampled sentences for a human to verify (human columns left blank)."""

import csv
import json
import random
from pathlib import Path

from judge import sentences

E = Path(__file__).parent
rows = [json.loads(x) for x in (E / "results/runs/test_agent_qwen.jsonl").read_text().splitlines()]
items = {i["id"]: i for i in json.loads((E / "companies/set.json").read_text())["items"]}
cands = [(r["id"], r["response"]["report"]) for r in rows if r["response"].get("report")]
rng = random.Random(11)
rng.shuffle(cands)
out = []
for rid, rep in cands:
    for s in sentences(rep["summary"]):
        out.append((rid, items[rid]["query"], rep["company"]["number"], s,
                    " | ".join(f"[{e['id']}] {e['excerpt'][:300]}" for e in rep["evidence"])))
rng.shuffle(out)
with (E / "hand_check.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["item_id", "query", "company_number", "sentence", "evidence_excerpts",
                "human_supported (yes/no/partial)", "human_notes"])
    for r in out[:20]:
        w.writerow([*r, "", ""])
print("wrote", min(20, len(out)), "rows")
