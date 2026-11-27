"""Score runs: routing, risk agreement vs snapshot oracle, faithfulness, cost/latency, bootstrap CIs."""

from __future__ import annotations

import json
import random
import re
import statistics
from pathlib import Path
from typing import Any

from judge import judge_rows
from snapshot import Store, load_all_items

from companylens.agent.risk import assess_risk

RESULTS = Path(__file__).parent / "results"
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def load_items() -> dict[str, dict[str, Any]]:
    return {i["id"]: i for i in load_all_items()}


def oracle(store: Store, number: str) -> tuple[str, set[str]] | None:
    def d(tool: str) -> dict[str, Any] | None:
        for k, v in store.data.items():
            if k.startswith(tool + "|") and f'"{number.lower()}"' in k.lower() and v["ok"]:
                return v["data"]  # type: ignore[no-any-return]
        return None

    prof = d("get_company_profile")
    if prof is None:
        return None
    r = assess_risk(
        prof, d("get_officers"), d("get_psc"), d("get_charges"), d("get_insolvency"), None, {}
    )
    return str(r.risk_level), {f.rule_id for f in r.red_flags}


def boot_ci(xs: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    if not xs:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return statistics.fmean(xs), means[int(0.025 * n)], means[int(0.975 * n)]


_WORDS = {
    w: str(i)
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen twenty".split()
    )
}
_DATE = re.compile(
    r"\b(\d{1,2}) (?:January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})",
    re.I,
)


def unsupported_numbers(rep: dict[str, Any]) -> tuple[int, int]:
    ev = " ".join(e["excerpt"] for e in rep["evidence"]) + " " + json.dumps(rep["facts"])
    ev_nums = {m.replace(",", "") for m in _NUM.findall(ev)}
    summ = re.sub(r"\[e\d+\]", "", rep["summary"])
    summ = _DATE.sub(lambda m: m.group(2), summ)
    summ = re.sub(
        r"\b(" + "|".join(_WORDS) + r")\b", lambda m: _WORDS[m.group(1).lower()], summ, flags=re.I
    )
    nums = [m.replace(",", "") for m in _NUM.findall(summ)]
    return sum(1 for n in nums if n not in ev_nums), len(nums)


async def score(split: str, config: str, use_judge: bool = True) -> dict[str, Any]:
    items = load_items()
    store = Store(None)
    rows = [
        json.loads(line)
        for line in (RESULTS / "runs" / f"{split}_{config}.jsonl").read_text().splitlines()
    ]
    verdicts = await judge_rows(rows, f"{split}_{config}") if use_judge else {}
    per: list[dict[str, Any]] = []
    for r in rows:
        it, resp = items[r["id"]], r["response"]
        cat = it["category"]
        rep = resp.get("report")
        exp_type = it.get("expected_type", "report")
        route_ok = resp["type"] == exp_type and (
            exp_type != "report"
            or (rep is not None and rep["company"]["number"] == it["expected_number"])
        )
        row: dict[str, Any] = {
            "id": r["id"],
            "category": cat,
            "route_ok": route_ok,
            "type": resp["type"],
            "exception": bool(r["exception"]),
            "wall_s": r["wall_s"],
        }
        if rep is not None:
            s = rep["stats"]
            row.update(
                cost=s["cost_gbp"],
                latency=s["latency_ms"] / 1000,
                tools=s["tool_calls"],
                rounds=s["llm_rounds"],
                complete=s["stop_reason"] == "complete",
                cc_path=s.get("claim_check_path"),
            )
            if route_ok:
                o = oracle(store, it["expected_number"])
                if o:
                    level, flags = o
                    got = {f["rule_id"] for f in rep["red_flags"]}
                    row.update(
                        risk_ok=rep["risk_level"] == level,
                        tp=len(got & flags),
                        fp=len(got - flags),
                        fn=len(flags - got),
                    )
            bad, tot = unsupported_numbers(rep)
            row.update(num_bad=bad, num_tot=tot)
            v = verdicts.get(f"{split}_{config}|{r['id']}")
            if v and v.get("ok", True) and v["n"]:
                row.update(sent_bad=v["unsupported"], sent_tot=v["n"], judge_cost=v["cost"])
        per.append(row)

    def col(k: str, cond: Any = lambda r: True) -> list[float]:
        return [float(r[k]) for r in per if k in r and cond(r)]

    def rate(k: str, tot: str) -> float:
        t = sum(r.get(tot, 0) for r in per)
        return sum(r.get(k, 0) for r in per) / t if t else float("nan")

    tp, fp, fn = (sum(r.get(k, 0) for r in per) for k in ("tp", "fp", "fn"))
    out: dict[str, Any] = {
        "config": config,
        "split": split,
        "n": len(per),
        "route_acc": boot_ci([float(r["route_ok"]) for r in per]),
        "route_by_category": {
            c: round(statistics.fmean(float(r["route_ok"]) for r in per if r["category"] == c), 3)
            for c in sorted({r["category"] for r in per})
        },
        "risk_agree": boot_ci(col("risk_ok")),
        "flag_recall": tp / (tp + fn) if tp + fn else None,
        "flag_precision": tp / (tp + fp) if tp + fp else None,
        "unsupported_sentence_rate": rate("sent_bad", "sent_tot"),
        "reports_with_unsupported_sentence": boot_ci(
            [float(r["sent_bad"] > 0) for r in per if "sent_bad" in r]
        ),
        "unsupported_number_rate": rate("num_bad", "num_tot"),
        "cost_gbp_mean": boot_ci(col("cost")),
        "latency_s_mean": boot_ci(col("latency")),
        "latency_s_p95": sorted(col("latency"))[int(0.95 * (len(col("latency")) - 1))]
        if col("latency")
        else None,
        "tool_calls_mean": boot_ci(col("tools")),
        "llm_rounds_mean": boot_ci(col("rounds")),
        "complete_rate": statistics.fmean(col("complete")) if col("complete") else None,
        "exceptions": sum(r["exception"] for r in per),
        "claim_check_paths": {
            p: sum(1 for r in per if r.get("cc_path") == p)
            for p in ("passed", "repaired", "dropped")
        },
        "judge_cost_gbp": sum(col("judge_cost")),
    }
    (RESULTS / f"metrics_{split}_{config}.json").write_text(
        json.dumps({"summary": out, "per_item": per}, indent=1)
    )
    return out
