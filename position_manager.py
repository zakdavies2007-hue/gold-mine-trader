from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from trading_config import TradingConfig


@dataclass(frozen=True)
class ExitDecision:
    action: str
    reason: Optional[str] = None


class PositionManager:
    def __init__(self, config: TradingConfig):
        self.config = config

    def can_open_position(self, *, account_equity: float, daily_pnl: float, open_positions: int) -> bool:
        if open_positions >= self.config.max_active_positions:
            return False
        if daily_pnl <= -(account_equity * self.config.max_daily_loss_percent):
            return False
        return True

    def calculate_quantity(self, *, price: float, account_equity: float) -> int:
        if price <= 0:
            return 0
        max_capital = min(account_equity * self.config.max_position_size, account_equity * self.config.risk_per_trade)
        quantity = int(max_capital // price)
        return max(quantity, 0)

    def build_exit_levels(self, entry_price: float) -> Dict[str, float]:
        stop_loss = entry_price * (1 - self.config.stop_loss_percent)
        take_profit = entry_price * (1 + self.config.take_profit_percent)
        return {'stop_loss': stop_loss, 'take_profit': take_profit}

    def evaluate_exit(self, position: Dict, current_price: float, now: Optional[datetime] = None) -> ExitDecision:
        now = now or datetime.now(timezone.utc)
        opened_at = datetime.fromisoformat(position['opened_at'])
        if current_price <= float(position['stop_loss']):
            return ExitDecision('sell', 'stop_loss')
        if current_price >= float(position['take_profit']):
            return ExitDecision('sell', 'take_profit')
        if now - opened_at >= timedelta(seconds=self.config.position_hold_time):
            return ExitDecision('sell', 'max_hold_time')
        return ExitDecision('hold')
