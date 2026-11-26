"""Shared test setup: tests must never see real credentials or hit the network."""

import pytest

from companylens.observability import Tracer

_KEYS = [
    "COMPANIES_HOUSE_API_KEY",
    "NEBIUS_API_KEY",
    "MISTRAL_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "FCA_API_KEY",
    "FCA_API_EMAIL",
]


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank credentials that .env may provide so tracers and clients stay offline."""
    for k in _KEYS:
        monkeypatch.setenv(k, "")


@pytest.fixture(autouse=True)
def _no_background_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop tracer flush threads from leaking HTTP calls into later tests."""
    monkeypatch.setattr(Tracer, "_flush", lambda self, trace_id: None)
