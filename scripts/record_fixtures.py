"""Copy 8 companies' tool outputs from the eval snapshot into tests/fixtures (no personal data: tools return aggregates)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
SNAP = ROOT / "eval" / "snapshots" / "snapshot.json"
OUT = ROOT / "tests" / "fixtures" / "companies.json"
NUMBERS = [
    "00445790",
    "09446231",
    "00502851",
    "07712220",
    "09563205",
    "02468686",
    "07524813",
    "01833679",
]


def main() -> None:
    data = json.loads(SNAP.read_text())
    keep = {
        k: v
        for k, v in data.items()
        if any(f'"{n}"' in k for n in NUMBERS) or (k.startswith("search_companies") and False)
    }
    OUT.write_text(json.dumps(keep, indent=1, sort_keys=True))
    print(len(keep), "entries ->", OUT)


if __name__ == "__main__":
    main()
