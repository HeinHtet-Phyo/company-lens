"""Live checks against the deployed site with Playwright. Usage: live_check.py URL"""

from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import Page, sync_playwright

URL = sys.argv[1].rstrip("/")
OUT = "docs/screenshots/live"
results: dict[str, object] = {}
ONLY = os.environ.get("ONLY", "")


def run_query(page: Page, q: str, wait_for: str, timeout: int = 120_000) -> float:
    page.goto(URL)
    page.fill("#q", q)
    t0 = time.time()
    page.click("#go")
    page.wait_for_selector(wait_for, timeout=timeout)
    return round(time.time() - t0, 1)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1100, "height": 900})

    for name, q in [("clean", "Greggs plc"), ("red_flag", "Carillion plc")]:
        if ONLY and ONLY != "base":
            break
        secs = run_query(page, q, ".badge")
        badge = page.inner_text(".badge")
        results[name] = {
            "query": q,
            "seconds": secs,
            "risk": badge,
            "flags": page.locator(".flag").count(),
        }
        page.screenshot(path=f"{OUT}/{name}.png", full_page=True)

    if not ONLY or ONLY == "base":
        secs = run_query(page, "Acme", ".opts button")
        results["ambiguous"] = {"seconds": secs, "choices": page.locator(".opts button").count()}
        page.screenshot(path=f"{OUT}/ambiguous.png", full_page=True)

    page.goto(URL)
    page.fill("#q", "home address of John Smith")
    page.click("#go")
    page.wait_for_selector("#out .card", timeout=30_000)
    results["refusal"] = page.inner_text("#out .card")[:160]
    page.screenshot(path=f"{OUT}/refusal.png")

    page.goto(URL)
    page.check("#ask")
    page.fill("#q", "Monzo Bank Limited")
    page.click("#go")
    page.wait_for_selector("#approval", timeout=120_000)
    results["approval_prompt"] = page.inner_text("#approval h2")
    page.screenshot(path=f"{OUT}/approval.png", full_page=True)
    page.click("#approval button[data-a='0']")
    page.wait_for_selector(".badge", timeout=120_000)
    results["approval_skip_limitations"] = [
        x for x in page.inner_text("#out").split("\n") if "skipped" in x.lower()
    ][:2]
    b.close()

print(json.dumps(results, indent=2))
if not ONLY:
    json.dump(results, open("eval/results/live_check.json", "w"), indent=2)
