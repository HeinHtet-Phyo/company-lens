"""Frozen tool outputs so every config sees identical data. Record once (live), then replay."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from companylens.config import get_settings
from companylens.models import ToolResult
from companylens.tools.company_tools import build_registry
from companylens.tools.registry import ToolDefinition, ToolRegistry

SNAP = Path(__file__).parent / "snapshots" / "snapshot.json"
SET = Path(__file__).parent / "companies" / "set.json"
PER_COMPANY = [
    "get_company_profile",
    "get_officers",
    "get_filing_history",
    "get_psc",
    "get_charges",
    "get_insolvency",
    "check_fca_register",
    "search_news",
]


def key(tool: str, args: dict[str, Any]) -> str:
    """Stable key; ignores limits/paging args and case of free-text args."""
    a = {
        k: (v.lower().strip() if isinstance(v, str) else v)
        for k, v in args.items()
        if k not in ("limit", "days")
    }
    return tool + "|" + json.dumps(a, sort_keys=True)


class Store:
    """JSON-backed map of key -> ToolResult. ``live`` registry fills misses when provided."""

    def __init__(self, live: ToolRegistry | None = None) -> None:
        self.data: dict[str, dict[str, Any]] = json.loads(SNAP.read_text()) if SNAP.exists() else {}
        self.live = live
        self.misses = 0

    def save(self) -> None:
        SNAP.parent.mkdir(exist_ok=True)
        SNAP.write_text(json.dumps(self.data, indent=0, default=str))

    async def call(self, tool: str, **args: Any) -> ToolResult:
        k = key(tool, args)
        if k not in self.data:
            self.misses += 1
            if self.live is None:
                return ToolResult(
                    tool=tool,
                    args=args,
                    ok=False,
                    source_url="snapshot://miss",
                    retrieved_at=_epoch(),
                    error="not in snapshot",
                )
            res = await self.live.get(tool).fn(**args)
            self.data[k] = json.loads(res.model_dump_json())
        return ToolResult.model_validate(self.data[k])

    def registry(self, base: ToolRegistry) -> ToolRegistry:
        """A registry with the same schemas whose functions read from this store."""
        reg = ToolRegistry()
        for d in base.all_tools():

            def make(name: str) -> Any:
                async def fn(**kw: Any) -> ToolResult:
                    return await self.call(name, **kw)

                return fn

            reg.register(ToolDefinition(d.name, d.description, d.parameters, make(d.name)))
        return reg


def _epoch() -> Any:
    from datetime import UTC, datetime

    return datetime(2026, 1, 1, tzinfo=UTC)


async def record() -> None:
    live = build_registry(get_settings())
    store = Store(live)
    items = json.loads(SET.read_text())["items"]
    sem = asyncio.Semaphore(3)

    async def one(it: dict[str, Any]) -> None:
        async with sem:
            cat = it["category"]
            if cat in ("unique_name", "ambiguous", "nonexistent"):
                await store.call("search_companies", query=it["query"])
            if cat in ("unique_name", "number"):
                n = it["expected_number"]
                prof = await store.call("get_company_profile", company_number=n)
                name = (prof.data or {}).get("company_name", it["query"])
                for t in PER_COMPANY[1:]:
                    if t in ("check_fca_register", "search_news"):
                        await store.call(
                            t,
                            company_name=name,
                            **({"company_number": n} if t == "check_fca_register" else {}),
                        )
                    else:
                        await store.call(t, company_number=n)
            if cat == "ambiguous":
                res = await store.call("search_companies", query=it["query"])
                for c in (res.data or {}).get("candidates", [])[:3]:
                    await store.call("get_company_profile", company_number=c["number"])

    await asyncio.gather(*(one(i) for i in items))
    store.save()
    for it in items:  # GDELT allows ~1 request / 5 s: fetch news sequentially, retry failures
        if it["category"] not in ("unique_name", "number"):
            continue
        prof = await store.call("get_company_profile", company_number=it["expected_number"])
        name = (prof.data or {}).get("company_name", it["query"])
        k = key("search_news", {"company_name": name})
        for _ in range(3):
            if k in store.data and store.data[k]["ok"]:
                break
            store.data.pop(k, None)
            await store.call("search_news", company_name=name)
            await asyncio.sleep(7)
    store.save()
    print("recorded", len(store.data), "entries")


if __name__ == "__main__":
    asyncio.run(record())
