"""Independent sentence-level faithfulness judge (different model family from the agent)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from companylens.config import AgentConfig, get_settings
from companylens.llm import LLMClient

JUDGE_MODEL = "google/gemma-3-27b-it"
CACHE = Path(__file__).parent / "results" / "judge_cache.json"
_PROMPT = (
    "You are a strict fact-checker. Given EVIDENCE excerpts and numbered SENTENCES from a report, "
    "decide for each sentence whether every factual claim in it is directly supported by the "
    'evidence. Reply with JSON only: {"verdicts": [{"i": 0, "supported": true}, ...]}. '
    "A sentence with any claim not in the evidence is unsupported. Citations like [e1] are not claims."
)


def sentences(summary: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\[])", summary.strip())
    return [p for p in parts if len(p.split()) >= 3]


def judge_client() -> LLMClient:
    cfg = AgentConfig(
        "judge", "nebius", JUDGE_MODEL, JUDGE_MODEL, JUDGE_MODEL, use_claim_check=False
    )
    return LLMClient(cfg, get_settings())


async def judge_report(report: dict[str, Any], llm: LLMClient) -> dict[str, Any]:
    sents = sentences(report["summary"])
    if not sents:
        return {"n": 0, "unsupported": 0, "cost": 0.0}
    ev = "\n".join(f"[{e['id']}] {e['tool']}: {e['excerpt']}" for e in report["evidence"])
    num = "\n".join(f"{i}. {s}" for i, s in enumerate(sents))
    try:
        msg, _, _, cost = await llm.chat(
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": f"EVIDENCE:\n{ev}\n\nSENTENCES:\n{num}"},
            ],
            temperature=0,
            model=JUDGE_MODEL,
            response_format={"type": "json_object"},
            max_tokens=600,
        )
    except Exception:
        return {"n": len(sents), "unsupported": 0, "cost": 0.0, "ok": False}
    try:
        text = re.sub(r"^```(?:json)?|```$", "", (msg.content or "").strip(), flags=re.M).strip()
        v = json.loads(text)["verdicts"]
        bad = sum(1 for x in v if not x.get("supported", True))
        return {"n": len(sents), "unsupported": bad, "cost": cost, "ok": True}
    except Exception:
        return {"n": len(sents), "unsupported": 0, "cost": cost, "ok": False}


async def judge_rows(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    cache: dict[str, Any] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    llm = judge_client()
    sem = asyncio.Semaphore(3)

    async def one(r: dict[str, Any]) -> None:
        k = f"{key}|{r['id']}"
        rep = r["response"].get("report")
        if rep is None or (k in cache and cache[k].get("ok")):
            return
        async with sem:
            cache[k] = await judge_report(rep, llm)

    await asyncio.gather(*(one(r) for r in rows))
    CACHE.write_text(json.dumps(cache))
    return {k: v for k, v in cache.items() if k.startswith(key + "|")}
