"""Stateless guard functions that check agent state against configured limits."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GuardConfig:
    max_tool_calls: int = 12
    max_llm_rounds: int = 6
    max_wall_seconds: float = 60.0
    max_cost_gbp: float = 0.02
    max_input_tokens_per_call: int = 32_000


@dataclass
class GuardResult:
    allowed: bool
    stop_reason: str | None = field(default=None)  # None if allowed
    message: str | None = field(default=None)


_OK = GuardResult(allowed=True)


class AgentGuards:
    """Stateless guard checks; each method returns a GuardResult."""

    def __init__(self, config: GuardConfig | None = None) -> None:
        self.config = config or GuardConfig()

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_tool_call_limit(self, tool_calls_so_far: int) -> GuardResult:
        if tool_calls_so_far >= self.config.max_tool_calls:
            return GuardResult(
                allowed=False,
                stop_reason="tool_call_limit",
                message=(
                    f"Tool call limit reached: {tool_calls_so_far} >= {self.config.max_tool_calls}."
                ),
            )
        return _OK

    def check_llm_round_limit(self, rounds_so_far: int) -> GuardResult:
        if rounds_so_far >= self.config.max_llm_rounds:
            return GuardResult(
                allowed=False,
                stop_reason="llm_round_limit",
                message=(
                    f"LLM round limit reached: {rounds_so_far} >= {self.config.max_llm_rounds}."
                ),
            )
        return _OK

    def check_time_limit(self, start_time: float) -> GuardResult:
        """*start_time* should be from ``time.monotonic()``."""
        elapsed = time.monotonic() - start_time
        if elapsed >= self.config.max_wall_seconds:
            return GuardResult(
                allowed=False,
                stop_reason="time_limit",
                message=(
                    f"Wall-clock time limit reached: {elapsed:.1f}s >= "
                    f"{self.config.max_wall_seconds}s."
                ),
            )
        return _OK

    def check_cost_limit(self, cost_gbp_so_far: float) -> GuardResult:
        if cost_gbp_so_far >= self.config.max_cost_gbp:
            return GuardResult(
                allowed=False,
                stop_reason="cost_limit",
                message=(
                    f"Cost limit reached: £{cost_gbp_so_far:.4f} >= "
                    f"£{self.config.max_cost_gbp:.4f}."
                ),
            )
        return _OK

    def check_loop_detection(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        call_history: list[tuple[str, dict[str, Any]]],
    ) -> GuardResult:
        """Block if the exact same (tool_name, tool_args) pair already appears in history."""
        for past_name, past_args in call_history:
            if past_name == tool_name and past_args == tool_args:
                return GuardResult(
                    allowed=False,
                    stop_reason="loop_detected",
                    message=(
                        f"Loop detected: tool '{tool_name}' called with identical "
                        f"arguments more than once."
                    ),
                )
        return _OK

    def check_tool_allowlist(self, tool_name: str, allowed_tools: set[str]) -> GuardResult:
        if tool_name not in allowed_tools:
            return GuardResult(
                allowed=False,
                stop_reason="tool_not_allowed",
                message=f"Tool '{tool_name}' is not in the allowlist.",
            )
        return _OK

    # ------------------------------------------------------------------
    # Composite check
    # ------------------------------------------------------------------

    def check_all(
        self,
        tool_calls_so_far: int,
        rounds_so_far: int,
        start_time: float,
        cost_gbp_so_far: float,
    ) -> GuardResult:
        """Run all limit checks in order; return the first failure or allowed."""
        for result in (
            self.check_tool_call_limit(tool_calls_so_far),
            self.check_llm_round_limit(rounds_so_far),
            self.check_time_limit(start_time),
            self.check_cost_limit(cost_gbp_so_far),
        ):
            if not result.allowed:
                return result
        return _OK
