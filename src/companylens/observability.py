"""Langfuse observability via REST batch ingestion. Non-blocking, fail-silent."""

from __future__ import annotations

import base64
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
        """Send traces to Langfuse REST batch endpoint. Swallows all errors."""
        try:
            with self._lock:
                meta = self._trace_meta.get(trace_id, {})
                spans = list(self._traces.get(trace_id, []))

            # Build Langfuse batch ingestion body
            batch: list[dict[str, Any]] = []

            # Trace event
            batch.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": "trace-create",
                    "timestamp": meta.get("timestamp", self._now_iso()),
                    "body": {
                        "id": meta.get("id", trace_id),
                        "name": meta.get("name", "unknown"),
                        "input": meta.get("input"),
                        "output": meta.get("output"),
                        "timestamp": meta.get("timestamp", self._now_iso()),
                    },
                }
            )

            # Span events
            for span in spans:
                batch.append(
                    {
                        "id": str(uuid.uuid4()),
                        "type": "span-create",
                        "timestamp": span.get("start_time", self._now_iso()),
                        "body": {
                            "id": span.get("id"),
                            "traceId": trace_id,
                            "name": span.get("name"),
                            "startTime": span.get("start_time"),
                            "endTime": span.get("end_time"),
                            "input": span.get("input"),
                            "output": span.get("output"),
                        },
                    }
                )

            credentials = base64.b64encode(
                f"{self._public_key}:{self._secret_key}".encode()
            ).decode()

            with httpx.Client(timeout=10.0) as client:
                client.post(
                    f"{self._host}/api/public/ingestion",
                    json={"batch": batch},
                    headers={
                        "Authorization": f"Basic {credentials}",
                        "Content-Type": "application/json",
                    },
                )
        except Exception as exc:
            print(f"[companylens] Langfuse flush error: {exc}", file=sys.stderr)
