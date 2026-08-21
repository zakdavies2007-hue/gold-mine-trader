"""
market_research.py – Numeric market-research metrics from OHLCV data.

All calculations are finite-safe: NaN, ±inf, zero-volume, and insufficient
data are handled explicitly.  Window sizes are configurable.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Defaults (overridden by config if available)
# ---------------------------------------------------------------------------
try:
    import config_advanced as _ca  # type: ignore[import]
    _VOLATILITY_WINDOW: int = getattr(_ca, "VOLATILITY_WINDOW", 20)
    _TREND_WINDOW: int = getattr(_ca, "TREND_WINDOW", 50)
    _SR_LOOKBACK: int = getattr(_ca, "SR_LOOKBACK", 100)
except Exception:
    _VOLATILITY_WINDOW = 20
    _TREND_WINDOW = 50
    _SR_LOOKBACK = 100


def _to_series(data: Any, column: str | None = None) -> pd.Series:
    """Coerce *data* to a float64 Series, dropping non-finite values."""
    if isinstance(data, pd.DataFrame):
        if column is None:
            raise ValueError("column must be specified when data is a DataFrame")
        s = data[column].astype(float)
    elif isinstance(data, pd.Series):
        s = data.astype(float)
    else:
        s = pd.Series(list(data), dtype=float)
    # Remove NaN and infinities
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    return s.reset_index(drop=True)


def _finite(value: float, fallback: float = 0.0) -> float:
    """Return *value* if it is finite, otherwise *fallback*."""
    if math.isfinite(value):
        return value
    return fallback


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------


def calculate_volatility(prices: Any, window: int | None = None) -> float:
    """Return the annualised daily-return standard deviation.

    Uses a sample (Bessel-corrected) standard deviation over *window* bars.
    Returns 0.0 when fewer than 2 valid data points are available.
    """
    w = window if window is not None else _VOLATILITY_WINDOW
    if w <= 0:
        raise ValueError(f"window must be positive, got {w}")
    s = _to_series(prices)
    if len(s) < 2:
        return 0.0
    tail = s.tail(w)
    if len(tail) < 2:
        return 0.0
    pct_changes = tail.pct_change().dropna()
    if pct_changes.empty:
        return 0.0
    std = float(pct_changes.std(ddof=1))
    # Annualise (252 trading days)
    annualised = std * math.sqrt(252)
    return _finite(annualised, 0.0)


def calculate_momentum(prices: Any, period: int = 5) -> float:
    """Return the *period*-bar price return (current / prior – 1).

    Returns 0.0 when insufficient data or division by zero.
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    s = _to_series(prices)
    if len(s) < period + 1:
        return 0.0
    current = float(s.iloc[-1])
    base = float(s.iloc[-(period + 1)])
    if base == 0:
        return 0.0
    return _finite((current - base) / base, 0.0)


def calculate_trend(prices: Any, window: int | None = None) -> float:
    """Return the OLS regression slope normalised by the mean price.

    Positive values indicate an uptrend; negative values a downtrend.
    Returns 0.0 when fewer than 2 valid data points are available.
    """
    w = window if window is not None else _TREND_WINDOW
    if w <= 0:
        raise ValueError(f"window must be positive, got {w}")
    s = _to_series(prices)
    if len(s) < 2:
        return 0.0
    tail = s.tail(w)
    if len(tail) < 2:
        return 0.0
    x = np.arange(len(tail), dtype=float)
    y = tail.values.astype(float)
    # OLS slope via numpy polyfit
    coeffs = np.polyfit(x, y, 1)
    slope = float(coeffs[0])
    mean_price = float(np.mean(y))
    if mean_price == 0:
        return 0.0
    return _finite(slope / mean_price, 0.0)


def calculate_volume_ratio(volumes: Any, window: int = 20) -> float:
    """Return current volume / average of prior *window* bars.

    Returns 1.0 (neutral) when insufficient data or zero average.
    Uses volumes[:-1] as the historical window so the current bar is excluded.
    """
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")
    s = _to_series(volumes)
    if len(s) < 2:
        return 1.0
    current = float(s.iloc[-1])
    history = s.iloc[:-1].tail(window)
    avg = float(history.mean())
    if avg == 0:
        return 1.0
    return _finite(current / avg, 1.0)


def calculate_support(lows: Any, window: int | None = None) -> float:
    """Return the minimum low over the look-back window as a support level."""
    w = window if window is not None else _SR_LOOKBACK
    if w <= 0:
        raise ValueError(f"window must be positive, got {w}")
    s = _to_series(lows)
    if s.empty:
        return 0.0
    return _finite(float(s.tail(w).min()), 0.0)


def calculate_resistance(highs: Any, window: int | None = None) -> float:
    """Return the maximum high over the look-back window as a resistance level."""
    w = window if window is not None else _SR_LOOKBACK
    if w <= 0:
        raise ValueError(f"window must be positive, got {w}")
    s = _to_series(highs)
    if s.empty:
        return 0.0
    return _finite(float(s.tail(w).max()), 0.0)


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


class MarketResearch:
    """Compute a complete set of market-research metrics from OHLCV data."""

    def __init__(
        self,
        volatility_window: int | None = None,
        trend_window: int | None = None,
        sr_lookback: int | None = None,
        volume_window: int = 20,
        momentum_period: int = 5,
    ) -> None:
        self.volatility_window = volatility_window or _VOLATILITY_WINDOW
        self.trend_window = trend_window or _TREND_WINDOW
        self.sr_lookback = sr_lookback or _SR_LOOKBACK
        self.volume_window = volume_window
        self.momentum_period = momentum_period

    def analyse(self, df: pd.DataFrame) -> dict[str, float]:
        """Return a metrics dict for the supplied OHLCV DataFrame.

        Expected columns: Close (or 'close'), High (or 'high'),
        Low (or 'low'), Volume (or 'volume').
        All returned values are finite floats.
        """
        def _col(name: str) -> pd.Series:
            for candidate in (name, name.capitalize(), name.upper(), name.lower()):
                if candidate in df.columns:
                    return df[candidate]
            raise KeyError(f"Column {name!r} not found in DataFrame: {list(df.columns)}")

        closes = _col("close")
        highs = _col("high")
        lows = _col("low")
        volumes = _col("volume")

        return {
            "volatility": calculate_volatility(closes, self.volatility_window),
            "momentum": calculate_momentum(closes, self.momentum_period),
            "trend": calculate_trend(closes, self.trend_window),
            "volume_ratio": calculate_volume_ratio(volumes, self.volume_window),
            "support": calculate_support(lows, self.sr_lookback),
            "resistance": calculate_resistance(highs, self.sr_lookback),
        }
