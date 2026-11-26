"""Run configs over the eval set against frozen snapshots. Test split is write-once.

Usage: python eval/run_eval.py --split dev --configs agent_qwen,baseline_fixed [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from snapshot import SET, Store

from companylens.agent.baseline import run_baseline
from companylens.agent.graph import CompanyAgent
from companylens.api.safety import REFUSAL_MESSAGE, check_input
from companylens.config import AGENT_CONFIGS, get_settings
from companylens.llm import LLMClient
from companylens.models import AgentResponse
from companylens.observability import Tracer
from companylens.tools.company_tools import build_registry

RESULTS = Path(__file__).parent / "results"
SPEND = RESULTS / "spend.json"
NUMBER_RE = re.compile(r"^(?=(?:.*\d){6})[A-Za-z0-9]{8}$")
SPEND_CAP_GBP = 8.0  # est. £8 ≈ $10 — hard stop well under the $15 Nebius budget


def log_spend(config: str, split: str, gbp: float) -> None:
    d: dict[str, Any] = (
        json.loads(SPEND.read_text()) if SPEND.exists() else {"total_gbp_est": 0.0, "entries": []}
    )
    d["total_gbp_est"] = round(d["total_gbp_est"] + gbp, 4)
    d["entries"].append({"config": config, "split": split, "gbp_est": round(gbp, 4)})
    d["note"] = "Estimated from token counts and a price table in llm.py, not provider invoices."
    SPEND.write_text(json.dumps(d, indent=1))


def total_spend() -> float:
    return float(json.loads(SPEND.read_text())["total_gbp_est"]) if SPEND.exists() else 0.0


async def run_item(
    item: dict[str, Any], cfg_name: str, store: Store, llm: LLMClient
) -> dict[str, Any]:
    cfg = AGENT_CONFIGS[cfg_name]
    reg = store.registry(build_registry(get_settings()))
    tracer = Tracer(get_settings())
    t0 = time.monotonic()
    err = None
    ok, msg = check_input(item["query"])
    if not ok:
        resp = AgentResponse(type="refused" if msg == REFUSAL_MESSAGE else "error", message=msg)
    else:
        try:
            if cfg.use_agent:
                resp = await CompanyAgent(reg, llm, cfg, tracer).run(item["query"])
            else:
                resp = await _baseline(item["query"], reg, llm, cfg, tracer)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"[:300]
            resp = AgentResponse(type="error", message=err)
    return {
        "id": item["id"],
        "config": cfg_name,
        "response": resp.model_dump(mode="json"),
        "exception": err,
        "wall_s": round(time.monotonic() - t0, 2),
    }


async def _baseline(q: str, reg: Any, llm: LLMClient, cfg: Any, tracer: Tracer) -> AgentResponse:
    """Fixed pipeline with naive resolution: number → direct, else top search hit."""
    q = q.strip()
    if NUMBER_RE.match(q):
        number, name = q.upper(), q.upper()
        prof = await reg.get("get_company_profile").fn(company_number=number)
        if not prof.ok:
            return AgentResponse(type="not_found", message="No such company.")
        name = (prof.data or {}).get("company_name", name)
    else:
        res = await reg.get("search_companies").fn(query=q)
        cands = (res.data or {}).get("candidates", []) if res.ok else []
        if not cands:
            return AgentResponse(type="not_found", message="No such company.")
        number, name = cands[0]["number"], cands[0]["name"]
    report = await run_baseline(number, name, reg, llm, cfg, tracer)
    return AgentResponse(type="report", report=report)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--configs", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--conc", type=int, default=4)
    a = ap.parse_args()
    items = [i for i in json.loads(SET.read_text())["items"] if i["split"] == a.split]
    if a.limit:
        items = items[: a.limit]
    store = Store(live=None)
    (RESULTS / "runs").mkdir(parents=True, exist_ok=True)
    for cfg_name in a.configs.split(","):
        out = RESULTS / "runs" / f"{a.split}_{cfg_name}.jsonl"
        if a.split == "test" and out.exists():
            print(f"REFUSING: {out} exists; the test split is run once per config.")
            continue
        if total_spend() >= SPEND_CAP_GBP:
            print("Spend cap reached; stopping.")
            return
        llm = LLMClient(AGENT_CONFIGS[cfg_name], get_settings())
        sem = asyncio.Semaphore(a.conc)

        async def guarded(
            it: dict[str, Any], c: str = cfg_name, m: LLMClient = llm
        ) -> dict[str, Any]:
            async with sem:
                return await run_item(it, c, store, m)

        t0 = time.time()
        rows = await asyncio.gather(*(guarded(i) for i in items))
        for r in rows:
            r["split"] = a.split
        out.write_text("\n".join(json.dumps(r) for r in rows))
        cost = sum(
            (r["response"].get("report") or {}).get("stats", {}).get("cost_gbp", 0.0) for r in rows
        )
        log_spend(cfg_name, a.split, cost)
        errs = sum(1 for r in rows if r["exception"])
        print(
            f"{cfg_name}/{a.split}: {len(rows)} items, {errs} exceptions, "
            f"est £{cost:.3f}, {time.time() - t0:.0f}s, snapshot misses {store.misses}"
        )


if __name__ == "__main__":
    asyncio.run(main())
