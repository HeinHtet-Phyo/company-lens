"""Unit tests for the observability / Tracer module."""

from __future__ import annotations

from companylens.config import Settings
from companylens.observability import Tracer, redact

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings_enabled() -> Settings:
    return Settings(
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
        langfuse_host="https://cloud.langfuse.com",
    )


def make_settings_disabled() -> Settings:
    return Settings(
        langfuse_public_key="",
        langfuse_secret_key="",
    )


# ---------------------------------------------------------------------------
# redact() tests
# ---------------------------------------------------------------------------


def test_redact_removes_email_addresses() -> None:
    text = "Contact us at jane.doe@example.com for more info."
    result = redact(text)
    assert "jane.doe@example.com" not in result
    assert "[REDACTED]" in result


def test_redact_removes_phone_numbers() -> None:
    text = "Call us on +44 20 7946 0958 for support."
    result = redact(text)
    assert "+44 20 7946 0958" not in result
    assert "[REDACTED]" in result


def test_redact_removes_names() -> None:
    text = "Director John Smith resigned last year."
    result = redact(text)
    # Names matching pattern Title Case Title Case should be redacted
    assert "John Smith" not in result


def test_redact_does_not_alter_plain_text() -> None:
    text = "The company is active and in good standing."
    result = redact(text)
    # No PII patterns; text should not add spurious REDACTED
    assert "REDACTED" not in result


def test_redact_handles_empty_string() -> None:
    assert redact("") == ""


# ---------------------------------------------------------------------------
# Tracer: start_trace
# ---------------------------------------------------------------------------


def test_start_trace_returns_string_trace_id() -> None:
    tracer = Tracer(make_settings_enabled())
    trace_id = tracer.start_trace("test_trace", {"company": "ACME"})
    assert isinstance(trace_id, str)
    assert len(trace_id) > 0


def test_start_trace_returns_unique_ids() -> None:
    tracer = Tracer(make_settings_enabled())
    id1 = tracer.start_trace("trace1", {})
    id2 = tracer.start_trace("trace2", {})
    assert id1 != id2


# ---------------------------------------------------------------------------
# Tracer: add_span
# ---------------------------------------------------------------------------


def test_add_span_returns_string_span_id() -> None:
    tracer = Tracer(make_settings_enabled())
    trace_id = tracer.start_trace("trace", {})
    span_id = tracer.add_span(trace_id, "my_span", {"input": "data"})
    assert isinstance(span_id, str)
    assert len(span_id) > 0


def test_add_span_returns_unique_ids() -> None:
    tracer = Tracer(make_settings_enabled())
    trace_id = tracer.start_trace("trace", {})
    span_id1 = tracer.add_span(trace_id, "span1", {})
    span_id2 = tracer.add_span(trace_id, "span2", {})
    assert span_id1 != span_id2


def test_end_span_does_not_raise() -> None:
    tracer = Tracer(make_settings_enabled())
    trace_id = tracer.start_trace("trace", {})
    span_id = tracer.add_span(trace_id, "span", {"k": "v"})
    # Should not raise
    tracer.end_span(trace_id, span_id, {"result": "done"})


def test_end_span_on_unknown_span_does_not_raise() -> None:
    tracer = Tracer(make_settings_enabled())
    trace_id = tracer.start_trace("trace", {})
    # Non-existent span_id — should silently do nothing
    tracer.end_span(trace_id, "nonexistent-span-id", {"result": "ok"})


# ---------------------------------------------------------------------------
# Tracer: disabled (empty keys)
# ---------------------------------------------------------------------------


def test_end_trace_does_not_raise_when_disabled() -> None:
    tracer = Tracer(make_settings_disabled())
    trace_id = tracer.start_trace("trace", {"input": "data"})
    tracer.add_span(trace_id, "span1", {"a": 1})
    # Should not raise even though Langfuse is disabled
    tracer.end_trace(trace_id, {"output": "done"})


def test_tracer_disabled_flag_when_keys_empty() -> None:
    tracer = Tracer(make_settings_disabled())
    assert tracer._enabled is False


def test_tracer_enabled_flag_when_keys_present() -> None:
    tracer = Tracer(make_settings_enabled())
    assert tracer._enabled is True


# ---------------------------------------------------------------------------
# Tracer: full flow (enabled, no actual HTTP)
# ---------------------------------------------------------------------------


def test_full_trace_flow_does_not_raise() -> None:
    """Complete trace flow should not raise even if HTTP would fail."""
    tracer = Tracer(make_settings_disabled())  # disabled so no HTTP
    trace_id = tracer.start_trace("full_flow", {"company_number": "12345678"})
    span_id = tracer.add_span(trace_id, "tool:get_profile", {"company_number": "12345678"})
    tracer.end_span(trace_id, span_id, {"ok": True})
    tracer.end_trace(trace_id, {"risk_level": "Low"})


def test_add_span_with_output_data() -> None:
    """add_span with output_data should not raise."""
    tracer = Tracer(make_settings_enabled())
    trace_id = tracer.start_trace("trace", {})
    span_id = tracer.add_span(
        trace_id, "span_with_output", {"input": "x"}, output_data={"output": "y"}
    )
    assert isinstance(span_id, str)
