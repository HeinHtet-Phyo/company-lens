"""Daily LLM spend budget that resets at UTC midnight."""

from __future__ import annotations

from datetime import UTC, date, datetime


class DailyBudget:
    """Track spend in GBP; ``exceeded`` is True once the daily cap is reached."""

    def __init__(self, limit_gbp: float) -> None:
        self.limit_gbp = limit_gbp
        self._day: date = datetime.now(UTC).date()
        self._spent = 0.0

    def _roll(self, today: date | None = None) -> None:
        d = today or datetime.now(UTC).date()
        if d != self._day:
            self._day, self._spent = d, 0.0

    def exceeded(self, today: date | None = None) -> bool:
        self._roll(today)
        return self._spent >= self.limit_gbp

    def add(self, gbp: float, today: date | None = None) -> None:
        self._roll(today)
        self._spent += gbp

    @property
    def spent(self) -> float:
        return self._spent
