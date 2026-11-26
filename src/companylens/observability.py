"""Langfuse observability via OTLP/JSON. Non-blocking, fail-silent."""

from __future__ import annotations

import base64
import json
import re
import sys
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from companylens.config import Settings

# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------

REDACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b"),  # Names (rough heuristic)
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # emails
    re.compile(r"\+?[\d\s\-\(\)]{7,15}"),  # phone numbers
]


def redact(text: str) -> str:
    """Replace officer/PSC names, emails and phone numbers with [REDACTED]."""
    for pattern in REDACT_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class Tracer:
    """Langfuse OTLP tracer. All sends are non-blocking (background thread). Fail-silent."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
        self._host = settings.langfuse_host
        self._public_key = settings.langfuse_public_key
        self._secret_key = settings.langfuse_secret_key
        # trace_id -> list of event dicts (Langfuse batch format)
        self._traces: dict[str, list[dict[str, Any]]] = {}
        self._trace_meta: dict[str, dict[str, Any]] = {}
        self._span_data: dict[str, dict[str, Any]] = {}  # span_id -> mutable span dict
        self._lock = threading.Lock()
        self.last_status: int | None = None

    def _now_iso(self) -> str:
        return datetime.now(tz=UTC).isoformat()

    def start_trace(self, name: str, input_data: dict[str, Any]) -> str:
        """Start a new trace. Returns trace_id."""
        trace_id = str(uuid.uuid4())
        with self._lock:
            self._traces[trace_id] = []
            self._trace_meta[trace_id] = {
                "id": trace_id,
                "name": name,
                "input": input_data,
                "timestamp": self._now_iso(),
            }
        return trace_id

    def add_span(
        self,
        trace_id: str,
        name: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any] | None = None,
    ) -> str:
        """Add a span to a trace. Returns span_id."""
        span_id = str(uuid.uuid4())
        span: dict[str, Any] = {
            "id": span_id,
            "trace_id": trace_id,
            "name": name,
            "start_time": self._now_iso(),
            "input": input_data,
        }
        if output_data is not None:
            span["output"] = output_data
            span["end_time"] = self._now_iso()

        with self._lock:
            self._span_data[span_id] = span
            if trace_id in self._traces:
                self._traces[trace_id].append(span)
        return span_id

    def end_span(self, trace_id: str, span_id: str, output_data: dict[str, Any]) -> None:
        """Complete a span with output data."""
        with self._lock:
            span = self._span_data.get(span_id)
            if span is not None:
                span["output"] = output_data
                span["end_time"] = self._now_iso()

    def end_trace(self, trace_id: str, output_data: dict[str, Any]) -> None:
        """End the trace and flush to Langfuse in background thread."""
        with self._lock:
            meta = self._trace_meta.get(trace_id)
            if meta is not None:
                meta["output"] = output_data
                meta["end_time"] = self._now_iso()

        if self._enabled:
            t = threading.Thread(target=self._flush, args=(trace_id,), daemon=True)
            t.start()

    def _flush(self, trace_id: str) -> None:
        """Send one trace to Langfuse via OTLP/JSON (/api/public/otel). Swallows all errors."""
        try:
            with self._lock:
                meta = dict(self._trace_meta.get(trace_id, {}))
                spans = [dict(sp) for sp in self._traces.get(trace_id, [])]
            tid = uuid.UUID(trace_id).hex
            root_id = tid[:16]

            def ns(iso: str | None) -> str:
                dt = datetime.fromisoformat(iso) if iso else datetime.now(tz=UTC)
                return str(int(dt.timestamp() * 1e9))

            def attrs(d: dict[str, Any]) -> list[dict[str, Any]]:
                return [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in d.items()
                    if v is not None
                ]

            otel_spans: list[dict[str, Any]] = [
                {
                    "traceId": tid,
                    "spanId": root_id,
                    "name": meta.get("name", "trace"),
                    "kind": 1,
                    "startTimeUnixNano": ns(meta.get("timestamp")),
                    "endTimeUnixNano": ns(meta.get("end_time")),
                    "attributes": attrs(
                        {
                            "langfuse.trace.name": meta.get("name", "trace"),
                            "langfuse.trace.input": json.dumps(meta.get("input"), default=str),
                            "langfuse.trace.output": json.dumps(meta.get("output"), default=str),
                        }
                    ),
                }
            ]
            for sp in spans:
                otel_spans.append(
                    {
                        "traceId": tid,
                        "spanId": uuid.UUID(sp["id"]).hex[:16],
                        "parentSpanId": root_id,
                        "name": sp.get("name", "span"),
                        "kind": 1,
                        "startTimeUnixNano": ns(sp.get("start_time")),
                        "endTimeUnixNano": ns(sp.get("end_time") or sp.get("start_time")),
                        "attributes": attrs(
                            {
                                "langfuse.observation.input": json.dumps(
                                    sp.get("input"), default=str
                                ),
                                "langfuse.observation.output": json.dumps(
                                    sp.get("output"), default=str
                                ),
                            }
                        ),
                    }
                )
            body = {
                "resourceSpans": [
                    {
                        "resource": {"attributes": attrs({"service.name": "companylens"})},
                        "scopeSpans": [{"scope": {"name": "companylens"}, "spans": otel_spans}],
                    }
                ]
            }
            credentials = base64.b64encode(
                f"{self._public_key}:{self._secret_key}".encode()
            ).decode()
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self._host}/api/public/otel/v1/traces",
                    json=body,
                    headers={
                        "Authorization": f"Basic {credentials}",
                        "Content-Type": "application/json",
                        "x-langfuse-ingestion-version": "4",
                    },
                )
                self.last_status = resp.status_code
                if resp.status_code >= 300:
                    print(f"[companylens] Langfuse HTTP {resp.status_code}", file=sys.stderr)
        except Exception as exc:
            print(f"[companylens] Langfuse flush error: {type(exc).__name__}", file=sys.stderr)
