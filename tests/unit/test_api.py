"""API tests with a stubbed agent (no network)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from companylens.api import main
from companylens.api.budget import DailyBudget
from companylens.api.ratelimit import SlidingWindowLimiter
from companylens.models import AgentResponse


class StubAgent:
    def __init__(self, on_event: Any = None, boom: bool = False) -> None:
        self.on_event = on_event
        self.boom = boom

    async def run(self, query: str, run_id: str | None = None) -> AgentResponse:
        if self.boom:
            raise ValueError("kaboom")
        if self.on_event:
            await self.on_event({"event": "resolve", "data": {"q": query}})
        return AgentResponse(type="not_found", message="none")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main, "_limiter", SlidingWindowLimiter(10, 60))
    monkeypatch.setattr(main, "_budget", DailyBudget(0.5))
    monkeypatch.setattr(main, "_make_agent", lambda c, on_event=None, ra=False: StubAgent(on_event))
    return TestClient(main.app, raise_server_exceptions=False)


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_report_ok(client: TestClient) -> None:
    r = client.post("/report", json={"query": "Acme"})
    assert r.status_code == 200 and r.json()["type"] == "not_found"


def test_rate_limit_per_forwarded_ip(client: TestClient) -> None:
    h = {"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}
    codes = [
        client.post("/report", json={"query": "Acme"}, headers=h).status_code for _ in range(11)
    ]
    assert codes[:10] == [200] * 10 and codes[10] == 429
    other = client.post("/report", json={"query": "Acme"}, headers={"X-Forwarded-For": "9.9.9.9"})
    assert other.status_code == 200


def test_budget_exceeded_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    b = DailyBudget(0.1)
    b.add(0.2)
    monkeypatch.setattr(main, "_budget", b)
    assert client.post("/report", json={"query": "Acme"}).status_code == 503


def test_refusal_and_length(client: TestClient) -> None:
    r = client.post("/report", json={"query": "what is the home address of Mr Smith"})
    assert r.status_code == 200 and r.json()["type"] == "refused"
    assert client.post("/report", json={"query": "x"}).status_code == 400
    assert client.post("/report", json={"query": "a" * 200}).status_code == 400


def test_unknown_config(client: TestClient) -> None:
    assert client.post("/report", json={"query": "Acme", "config": "nope"}).status_code == 400
    assert (
        client.post("/report", json={"query": "Acme", "config": "baseline_fixed"}).status_code
        == 400
    )


def test_unhandled_error_json_has_exception_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_limiter", SlidingWindowLimiter(10, 60))
    monkeypatch.setattr(
        main, "_make_agent", lambda c, on_event=None, ra=False: StubAgent(on_event, True)
    )
    r = TestClient(main.app, raise_server_exceptions=False).post("/report", json={"query": "Acme"})
    assert r.status_code == 500
    assert r.json()["exception"] == "ValueError" and r.json()["type"] == "error"


def test_sse_event_order(client: TestClient) -> None:
    with client.stream("GET", "/report/stream", params={"q": "Acme"}) as r:
        body = "".join(r.iter_text())
    assert body.index("event: resolve") < body.index("event: report")


def test_sse_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_limiter", SlidingWindowLimiter(10, 60))
    monkeypatch.setattr(
        main, "_make_agent", lambda c, on_event=None, ra=False: StubAgent(on_event, True)
    )
    with TestClient(main.app).stream("GET", "/report/stream", params={"q": "Acme"}) as r:
        body = "".join(r.iter_text())
    assert "event: error" in body and "ValueError" in body


def test_index_served(client: TestClient) -> None:
    assert client.get("/").status_code == 200


class PausingAgent(StubAgent):
    def __init__(self, on_event: Any = None) -> None:
        super().__init__(on_event)
        self.decision: bool | None = None

    async def run(self, query: str, run_id: str | None = None) -> AgentResponse:
        return AgentResponse(
            type="approval_required",
            message="The agent wants to: search news",
            pending_actions=[{"tool": "search_news", "description": "search news"}],
        )

    async def resume(self, run_id: str, approve: bool) -> AgentResponse:
        self.decision = approve
        return AgentResponse(type="not_found", message=f"approved={approve}")


def test_approve_unknown_run_is_404(client: TestClient) -> None:
    r = client.post("/report/approve", json={"run_id": "nope", "approve": True})
    assert r.status_code == 404 and r.json()["type"] == "error"


def test_stream_emits_approval_event_and_times_out_to_skip(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = PausingAgent()
    monkeypatch.setattr(main, "_make_agent", lambda c, on_event=None, ra=False: agent)
    monkeypatch.setattr(main, "APPROVAL_TIMEOUT_S", 0.05)
    body = client.get("/report/stream?q=Acme&approve=true").text
    assert "event: approval_required" in body and "run_id" in body
    assert "approved=False" in body and agent.decision is False
