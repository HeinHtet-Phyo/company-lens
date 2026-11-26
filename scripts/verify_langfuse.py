"""Send one trace to Langfuse and confirm it can be read back. Prints status codes only, never keys."""

from __future__ import annotations

import base64
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from companylens.config import get_settings
from companylens.observability import Tracer


def main() -> None:
    s = get_settings()
    t = Tracer(s)
    tid = t.start_trace("verify", {"note": "companylens connectivity check"})
    sid = t.add_span(tid, "span", {"x": 1})
    t.end_span(tid, sid, {"ok": True})
    t.end_trace(tid, {"done": True})
    t._flush(tid)
    print("ingestion status:", t.last_status)
    auth = base64.b64encode(f"{s.langfuse_public_key}:{s.langfuse_secret_key}".encode()).decode()
    start = (datetime.now(UTC) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for _ in range(15):
        r = httpx.get(
            f"{s.langfuse_host}/api/public/v2/observations",
            params={"fields": "core,basic", "fromStartTime": start, "traceId": uuid.UUID(tid).hex},
            headers={"Authorization": f"Basic {auth}"},
        )
        n = len(r.json().get("data", [])) if r.status_code == 200 else 0
        if n:
            print("trace read back: OK, observations:", n)
            return
        time.sleep(4)
    print("trace not found; last status:", r.status_code)


if __name__ == "__main__":
    main()
