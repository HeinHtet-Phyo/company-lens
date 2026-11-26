"""CLI: python eval/score.py --split dev --configs a,b"""

import argparse
import asyncio
import json

from metrics import score


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True)
    ap.add_argument("--configs", required=True)
    a = ap.parse_args()
    for c in a.configs.split(","):
        s = await score(a.split, c)
        print(json.dumps(s, default=lambda x: round(x, 4) if isinstance(x, float) else x)[:1500])


asyncio.run(main())
