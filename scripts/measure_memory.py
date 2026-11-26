"""Run the container under --memory=512m, fire reports, record peak memory to eval/results/memory.json."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

NAME = "companylens-mem"
QUERIES = ["Monzo Bank", "00445790", "Greggs plc"]


def sh(*a: str) -> str:
    return subprocess.run(a, capture_output=True, text=True, check=False).stdout.strip()


def mem_mib() -> float:
    raw = (
        sh("docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", NAME)
        .split("/")[0]
        .strip()
    )
    num = float("".join(c for c in raw if c.isdigit() or c == "."))
    return num / 1024 if "KiB" in raw else num * 1024 if "GiB" in raw else num


def main() -> None:
    sh("docker", "rm", "-f", NAME)
    t0 = time.time()
    sh(
        "docker",
        "run",
        "-d",
        "--name",
        NAME,
        "--memory=512m",
        "-p",
        "8001:8000",
        "--env-file",
        ".env",
        "companylens:latest",
    )
    while time.time() - t0 < 60:
        try:
            urllib.request.urlopen("http://localhost:8001/health", timeout=2)
            break
        except Exception:
            time.sleep(0.5)
    cold_start = time.time() - t0
    idle = mem_mib()
    peak = idle
    for q in QUERIES:
        url = "http://localhost:8001/report/stream?q=" + urllib.parse.quote(q)
        with urllib.request.urlopen(url, timeout=120) as r:
            while r.read(1024):
                peak = max(peak, mem_mib())
    inspect = json.loads(sh("docker", "inspect", NAME))[0]
    oom = inspect["State"]["OOMKilled"]
    size = int(sh("docker", "image", "inspect", "companylens:latest", "--format", "{{.Size}}"))
    sh("docker", "rm", "-f", NAME)
    out = {
        "idle_mib": round(idle, 1),
        "peak_mib": round(peak, 1),
        "oom_killed": oom,
        "limit_mib": 512,
        "cold_start_s": round(cold_start, 1),
        "image_mb": round(size / 1e6),
        "queries": QUERIES,
    }
    Path("eval/results/memory.json").write_text(json.dumps(out, indent=2))
    print(out)


if __name__ == "__main__":
    main()
