from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class ResearchSnapshot:
    volatility: float
    momentum: float
    trend: float
    avg_volume: float
    volume_ratio: float
    support: float
    resistance: float

    def as_dict(self) -> Dict[str, float]:
        return {
            'volatility': self.volatility,
            'momentum': self.momentum,
            'trend': self.trend,
            'avg_volume': self.avg_volume,
            'volume_ratio': self.volume_ratio,
            'support': self.support,
            'resistance': self.resistance,
        }


class MarketResearch:
    def __init__(self, volatility_window: int = 20, trend_window: int = 50, support_window: int = 20):
        self.volatility_window = volatility_window
        self.trend_window = trend_window
        self.support_window = support_window

    def _series(self, data, key: str) -> List[float]:
        if data is None:
            return []
        if isinstance(data, dict):
            values = data.get(key, [])
        else:
            try:
                values = data[key]
            except Exception:
                return []
        return [float(value) for value in values if value is not None]

    def analyze(self, data) -> Dict[str, float]:
        closes = self._series(data, 'Close')
        if not closes:
            return ResearchSnapshot(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0).as_dict()

        volumes = self._series(data, 'Volume')
        returns = []
        for previous, current in zip(closes, closes[1:]):
            if previous:
                returns.append((current / previous) - 1.0)
        recent_returns = returns[-self.volatility_window:]
        if recent_returns:
            mean_return = sum(recent_returns) / len(recent_returns)
            volatility = sqrt(sum((item - mean_return) ** 2 for item in recent_returns) / len(recent_returns))
        else:
            volatility = 0.0

        momentum_base = closes[-min(5, len(closes))]
        momentum = float((closes[-1] / momentum_base) - 1.0) if momentum_base else 0.0

        trend_window = closes[-min(self.trend_window, len(closes)):]
        if len(trend_window) > 1:
            x_values = list(range(len(trend_window)))
            x_mean = sum(x_values) / len(x_values)
            y_mean = sum(trend_window) / len(trend_window)
            numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, trend_window))
            denominator = sum((x - x_mean) ** 2 for x in x_values) or 1.0
            slope = numerator / denominator
            trend = slope / max(y_mean, 1e-9)
        else:
            trend = 0.0

        recent_volumes = volumes[-self.volatility_window:]
        avg_volume = (sum(recent_volumes) / len(recent_volumes)) if recent_volumes else 0.0
        current_volume = volumes[-1] if volumes else 0.0
        volume_ratio = current_volume / avg_volume if avg_volume else 1.0

        lows = self._series(data, 'Low') or closes
        highs = self._series(data, 'High') or closes
        support_window = lows[-min(self.support_window, len(lows)):] if lows else []
        resistance_window = highs[-min(self.support_window, len(highs)):] if highs else []
        support = min(support_window) if support_window else 0.0
        resistance = max(resistance_window) if resistance_window else 0.0

        return ResearchSnapshot(
            volatility=volatility,
            momentum=momentum,
            trend=trend,
            avg_volume=avg_volume,
            volume_ratio=volume_ratio,
            support=support,
            resistance=resistance,
        ).as_dict()
