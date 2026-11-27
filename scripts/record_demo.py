"""Record the live site as a real video (Playwright) and convert it to docs/demo.gif with ffmpeg.

Usage: record_demo.py URL
Flow: Carillion plc (timeline fills, report with red flags) -> "Acme" (choice buttons).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

def convert(video: Path, m: dict[str, float]) -> None:
    """Cut and speed up the recording, then write docs/demo.gif (15-25 s, under 5 MB)."""
    # Segments: typing+click (real speed), agent wait (3x), report (real), ambiguous (real)
    filt = (
        f"[0:v]trim=0:{m['click']-0.5},setpts=PTS-STARTPTS[a];"
        f"[0:v]trim={m['click']-0.5}:{m['report']},setpts=(PTS-STARTPTS)/4[b];"
        f"[0:v]trim={m['report']}:{m['report_end']},setpts=PTS-STARTPTS[c];"
        f"[0:v]trim={m['amb_click']-1.0}:{m['end']-1.0},setpts=PTS-STARTPTS[d];"
        "[a][b][c][d]concat=n=4:v=1:a=0,fps=7,scale=760:-1:flags=lanczos,split[s0][s1];"
        "[s0]palettegen=max_colors=64[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-filter_complex", filt, "docs/demo.gif"],
        check=True,
    )
    print("size MB:", round(Path("docs/demo.gif").stat().st_size / 1e6, 2))


if len(sys.argv) > 2 and sys.argv[2] == '--convert':
    convert(next(Path('/tmp/companylens_demo').glob('*.webm')), json.loads(Path('/tmp/companylens_demo/marks.json').read_text()))
    raise SystemExit

URL = sys.argv[1].rstrip("/")
TMP = Path("/tmp/companylens_demo")
shutil.rmtree(TMP, ignore_errors=True)
marks: dict[str, float] = {}

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(
        viewport={"width": 900, "height": 640}, record_video_dir=str(TMP), record_video_size={"width": 900, "height": 640}
    )
    page = ctx.new_page()
    t0 = time.time()
    page.goto(URL)
    page.wait_for_selector("#q")
    page.wait_for_timeout(1000)
    page.click("#q")
    page.keyboard.type("Carillion plc", delay=60)
    page.wait_for_timeout(400)
    marks["click"] = time.time() - t0
    page.click("#go")
    page.wait_for_selector(".badge", timeout=120_000)
    marks["report"] = time.time() - t0
    page.wait_for_timeout(1200)
    page.locator("text=Red flags").first.scroll_into_view_if_needed()
    page.wait_for_timeout(3500)
    marks["report_end"] = time.time() - t0
    page.evaluate("window.scrollTo(0, 0)")
    page.fill("#q", "")
    page.click("#q")
    page.keyboard.type("Acme", delay=80)
    page.wait_for_timeout(300)
    marks["amb_click"] = time.time() - t0
    page.click("#go")
    page.wait_for_selector(".opts button", timeout=60_000)
    page.wait_for_timeout(500)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(3500)
    marks["end"] = time.time() - t0
    ctx.close()
    b.close()

video = next(TMP.glob("*.webm"))
print(json.dumps(marks, indent=1))
(TMP / 'marks.json').write_text(json.dumps(marks))
convert(video, marks)
