"""
position_manager.py – Stop-loss / take-profit / time-based exit logic.

Key design choices
------------------
* All timestamps use timezone-aware UTC datetimes.
* Exits are evaluated locally; they are NOT broker-native stop orders.
  (Local REST exits may not fire if the process crashes.)
* Position management continues outside market hours (time-based exits still fire).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import NamedTuple

log = logging.getLogger(__name__)

# Exit reasons
EXIT_STOP_LOSS = "stop_loss"
EXIT_TAKE_PROFIT = "take_profit"
EXIT_TIME = "time_limit"
EXIT_MANUAL = "manual"


class ExitDecision(NamedTuple):
    should_exit: bool
    reason: str
    exit_price: float


class PositionManager:
    """Evaluate whether an open position should be closed."""

    def __init__(
        self,
        stop_loss_pct: float = 0.05,
        take_profit_pct: float = 0.15,
        max_hold_seconds: int = 86400,
        capital: float = 500.0,
        max_active_positions: int = 5,
        max_daily_loss_pct: float = 0.05,
    ) -> None:
        for name, val in [
            ("stop_loss_pct", stop_loss_pct),
            ("take_profit_pct", take_profit_pct),
            ("max_daily_loss_pct", max_daily_loss_pct),
        ]:
            if not (0 < val <= 1):
                raise ValueError(f"{name}={val} must be a fraction in (0, 1]")
        if max_hold_seconds <= 0:
            raise ValueError("max_hold_seconds must be positive")
        if capital <= 0:
            raise ValueError("capital must be positive")

        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_hold_seconds = max_hold_seconds
        self.capital = capital
        self.max_active_positions = max_active_positions
        self.max_daily_loss_pct = max_daily_loss_pct

    # ------------------------------------------------------------------

    def evaluate_exit(
        self,
        entry_price: float,
        current_price: float,
        opened_at: str | datetime,
        side: str = "buy",
    ) -> ExitDecision:
        """Return an ExitDecision for the given position state.

        Works outside market hours (time-based exits still fire).
        """
        if not math.isfinite(entry_price) or entry_price <= 0:
            log.warning("Invalid entry_price=%s; skipping exit evaluation", entry_price)
            return ExitDecision(should_exit=False, reason="", exit_price=0.0)
        if not math.isfinite(current_price) or current_price <= 0:
            log.warning("Invalid current_price=%s; skipping exit evaluation", current_price)
            return ExitDecision(should_exit=False, reason="", exit_price=0.0)

        # Compute return
        if side == "buy":
            ret = (current_price - entry_price) / entry_price
        else:
            ret = (entry_price - current_price) / entry_price

        if not math.isfinite(ret):
            return ExitDecision(should_exit=False, reason="", exit_price=0.0)

        # Take-profit
        if ret >= self.take_profit_pct:
            return ExitDecision(True, EXIT_TAKE_PROFIT, current_price)

        # Stop-loss
        if ret <= -self.stop_loss_pct:
            return ExitDecision(True, EXIT_STOP_LOSS, current_price)

        # Time-based exit
        now = datetime.now(timezone.utc)
        try:
            if isinstance(opened_at, str):
                opened_dt = _parse_utc(opened_at)
            else:
                opened_dt = _ensure_aware(opened_at)
            age = (now - opened_dt).total_seconds()
            if age >= self.max_hold_seconds:
                return ExitDecision(True, EXIT_TIME, current_price)
        except Exception as exc:
            log.warning("Could not parse opened_at timestamp: %s", exc)

        return ExitDecision(False, "", current_price)

    # ------------------------------------------------------------------

    def position_size(
        self, capital: float, price: float, risk_pct: float = 0.10
    ) -> int:
        """Return the number of shares to buy given available capital."""
        if not math.isfinite(price) or price <= 0:
            return 0
        if not math.isfinite(capital) or capital <= 0:
            return 0
        budget = capital * risk_pct
        shares = int(budget / price)
        return max(shares, 0)

    def can_open_position(
        self,
        open_position_count: int,
        daily_pnl: float,
    ) -> tuple[bool, str]:
        """Return (can_open, reason_if_not)."""
        if open_position_count >= self.max_active_positions:
            return False, f"max_active_positions ({self.max_active_positions}) reached"
        loss_limit = self.capital * self.max_daily_loss_pct
        if daily_pnl <= -loss_limit:
            return False, f"daily loss limit (-{loss_limit:.2f}) reached"
        return True, ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_utc(ts: str) -> datetime:
    """Parse an ISO-8601 UTC string (with or without trailing Z) to an aware datetime."""
    s = ts.rstrip("Z").replace("+00:00", "")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Fallback for non-standard formats
        from dateutil import parser as dp  # type: ignore[import]
        dt = dp.parse(ts)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
