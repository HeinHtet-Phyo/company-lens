"""Re-fetch failed GDELT entries slowly (GDELT allows ~1 request / 5 s)."""

import asyncio
import json

from snapshot import Store

from companylens.config import get_settings
from companylens.tools.company_tools import build_registry


async def main() -> None:
    live = build_registry(get_settings())
    store = Store(live)
    todo = [k for k, v in store.data.items() if k.startswith("search_news") and not v["ok"]]
    for i, k in enumerate(todo):
        args = json.loads(k.split("|", 1)[1])
        for attempt in range(3):
            res = await live.get("search_news").fn(**args)
            if res.ok:
                store.data[k] = json.loads(res.model_dump_json())
                break
            await asyncio.sleep(8)
        await asyncio.sleep(6)
        if i % 10 == 9:
            store.save()
    store.save()
    ok = sum(v["ok"] for k, v in store.data.items() if k.startswith("search_news"))
    print("news ok", ok, "of", sum(k.startswith("search_news") for k in store.data))


asyncio.run(main())
