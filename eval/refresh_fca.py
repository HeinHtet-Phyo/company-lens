"""Re-record ONLY the FCA Register snapshot entries (run once FCA credentials exist).

Usage: python eval/refresh_fca.py   # then re-run the FCA-affected experiment (see docs/eval_method.md)
"""

import asyncio
import json
import sys

from snapshot import SET, Store

from companylens.config import get_settings
from companylens.tools.company_tools import build_registry


async def main() -> None:
    s = get_settings()
    if not (s.fca_api_email and s.fca_api_key):
        sys.exit("FCA credentials not configured (FCA_API_EMAIL / FCA_API_KEY in .env). Nothing to do.")
    live = build_registry(s)
    store = Store(live)
    items = [i for i in json.loads(SET.read_text())["items"] if i["category"] in ("unique_name", "number")]
    done = 0
    for it in items:
        n = it["expected_number"]
        prof = await store.call("get_company_profile", company_number=n)
        name = (prof.data or {}).get("company_name", it["query"])
        sic = (prof.data or {}).get("sic_codes") or []
        if not any(str(c).startswith(("64", "65", "66")) for c in sic):
            continue
        from snapshot import key

        store.data.pop(key("check_fca_register", {"company_name": name, "company_number": n}), None)
        await store.call("check_fca_register", company_name=name, company_number=n)
        done += 1
    store.save()
    print("refreshed FCA entries for", done, "financial-SIC companies")


asyncio.run(main())
