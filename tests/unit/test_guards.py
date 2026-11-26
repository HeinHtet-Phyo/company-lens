"""Unit tests for AgentGuards (guards.py)."""

from __future__ import annotations

import time

import pytest

from companylens.agent.guards import AgentGuards, GuardConfig


@pytest.fixture()
def guards() -> AgentGuards:
    return AgentGuards(
        GuardConfig(
            max_tool_calls=5,
            max_llm_rounds=3,
            max_wall_seconds=10.0,
            max_cost_gbp=0.01,
            max_input_tokens_per_call=1000,
        )
    )


# ---------------------------------------------------------------------------
# Individual limit checks
# ---------------------------------------------------------------------------


class TestToolCallLimit:
    def test_at_limit_not_allowed(self, guards: AgentGuards):
        result = guards.check_tool_call_limit(5)
        assert result.allowed is False
        assert result.stop_reason == "tool_call_limit"

    def test_below_limit_allowed(self, guards: AgentGuards):
        result = guards.check_tool_call_limit(4)
        assert result.allowed is True

    def test_message_contains_counts(self, guards: AgentGuards):
        result = guards.check_tool_call_limit(5)
        assert "5" in (result.message or "")


class TestLLMRoundLimit:
    def test_at_limit_not_allowed(self, guards: AgentGuards):
        result = guards.check_llm_round_limit(3)
        assert result.allowed is False
        assert result.stop_reason == "llm_round_limit"

    def test_below_limit_allowed(self, guards: AgentGuards):
        result = guards.check_llm_round_limit(2)
        assert result.allowed is True


class TestTimeLimit:
    def test_expired_not_allowed(self, guards: AgentGuards):
        past = time.monotonic() - 15.0  # 15 s ago → over 10 s limit
        result = guards.check_time_limit(past)
        assert result.allowed is False
        assert result.stop_reason == "time_limit"

    def test_within_limit_allowed(self, guards: AgentGuards):
        now = time.monotonic()
        result = guards.check_time_limit(now)
        assert result.allowed is True


class TestCostLimit:
    def test_at_limit_not_allowed(self, guards: AgentGuards):
        result = guards.check_cost_limit(0.01)
        assert result.allowed is False
        assert result.stop_reason == "cost_limit"

    def test_below_limit_allowed(self, guards: AgentGuards):
        result = guards.check_cost_limit(0.009)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Loop detection
# ---------------------------------------------------------------------------


class TestLoopDetection:
    def test_same_tool_same_args_blocked(self, guards: AgentGuards):
        history = [("get_profile", {"number": "12345678"})]
        result = guards.check_loop_detection("get_profile", {"number": "12345678"}, history)
        assert result.allowed is False
        assert result.stop_reason == "loop_detected"

    def test_same_tool_different_args_allowed(self, guards: AgentGuards):
        history = [("get_profile", {"number": "12345678"})]
        result = guards.check_loop_detection("get_profile", {"number": "99999999"}, history)
        assert result.allowed is True

    def test_empty_history_allowed(self, guards: AgentGuards):
        result = guards.check_loop_detection("get_profile", {"number": "12345678"}, [])
        assert result.allowed is True

    def test_different_tool_same_args_allowed(self, guards: AgentGuards):
        history = [("get_profile", {"number": "12345678"})]
        result = guards.check_loop_detection("get_officers", {"number": "12345678"}, history)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Allowlist check
# ---------------------------------------------------------------------------


class TestToolAllowlist:
    def test_not_in_allowlist_blocked(self, guards: AgentGuards):
        result = guards.check_tool_allowlist("dangerous_tool", {"get_profile", "get_officers"})
        assert result.allowed is False
        assert result.stop_reason == "tool_not_allowed"

    def test_in_allowlist_allowed(self, guards: AgentGuards):
        result = guards.check_tool_allowlist("get_profile", {"get_profile", "get_officers"})
        assert result.allowed is True


# ---------------------------------------------------------------------------
# check_all composite
# ---------------------------------------------------------------------------


class TestCheckAll:
    def test_all_ok(self, guards: AgentGuards):
        result = guards.check_all(
            tool_calls_so_far=1,
            rounds_so_far=1,
            start_time=time.monotonic(),
            cost_gbp_so_far=0.001,
        )
        assert result.allowed is True

    def test_first_failure_returned(self, guards: AgentGuards):
        """Tool call limit hit first even when other limits are also exceeded."""
        past = time.monotonic() - 20.0
        result = guards.check_all(
            tool_calls_so_far=10,  # over tool limit
            rounds_so_far=10,  # over round limit too
            start_time=past,  # over time limit too
            cost_gbp_so_far=1.0,  # over cost limit too
        )
        assert result.allowed is False
        assert result.stop_reason == "tool_call_limit"

    def test_only_time_limit_hit(self, guards: AgentGuards):
        past = time.monotonic() - 15.0
        result = guards.check_all(
            tool_calls_so_far=1,
            rounds_so_far=1,
            start_time=past,
            cost_gbp_so_far=0.001,
        )
        assert result.allowed is False
        assert result.stop_reason == "time_limit"
