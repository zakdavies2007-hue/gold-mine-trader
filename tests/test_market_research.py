"""
tests/test_market_research.py – MarketResearch numeric metrics tests.
"""
import math
import unittest

import numpy as np
import pandas as pd

from market_research import (
    MarketResearch,
    calculate_momentum,
    calculate_trend,
    calculate_volatility,
    calculate_volume_ratio,
    calculate_support,
    calculate_resistance,
)


def _make_df(closes, highs=None, lows=None, volumes=None):
    n = len(closes)
    return pd.DataFrame({
        "close": closes,
        "high": highs if highs is not None else [c * 1.01 for c in closes],
        "low": lows if lows is not None else [c * 0.99 for c in closes],
        "volume": volumes if volumes is not None else [1000.0] * n,
    })


class TestVolatility(unittest.TestCase):

    def test_rising_prices(self):
        prices = list(range(1, 52))  # 51 values
        v = calculate_volatility(prices, window=20)
        self.assertTrue(math.isfinite(v))
        self.assertGreaterEqual(v, 0)

    def test_flat_prices(self):
        prices = [100.0] * 25
        v = calculate_volatility(prices, window=20)
        self.assertEqual(v, 0.0)

    def test_empty_prices(self):
        self.assertEqual(calculate_volatility([], window=5), 0.0)

    def test_single_value(self):
        self.assertEqual(calculate_volatility([100.0], window=5), 0.0)

    def test_nan_values_handled(self):
        import numpy as np
        prices = [100.0, float("nan"), 102.0, float("nan"), 104.0, 106.0, 108.0]
        v = calculate_volatility(prices, window=5)
        self.assertTrue(math.isfinite(v))

    def test_infinity_handled(self):
        prices = [100.0, float("inf"), 102.0, 104.0, 106.0]
        v = calculate_volatility(prices, window=4)
        self.assertTrue(math.isfinite(v))

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            calculate_volatility([1, 2, 3], window=0)


class TestMomentum(unittest.TestCase):

    def test_rising(self):
        prices = list(range(10, 20))
        m = calculate_momentum(prices, period=5)
        self.assertGreater(m, 0)

    def test_falling(self):
        prices = list(range(20, 10, -1))
        m = calculate_momentum(prices, period=5)
        self.assertLess(m, 0)

    def test_flat(self):
        prices = [100.0] * 10
        self.assertEqual(calculate_momentum(prices, period=5), 0.0)

    def test_insufficient_data(self):
        self.assertEqual(calculate_momentum([100.0], period=5), 0.0)

    def test_nan_handled(self):
        prices = [100.0, float("nan"), 102.0, float("nan"), 104.0, 106.0]
        m = calculate_momentum(prices, period=3)
        self.assertTrue(math.isfinite(m))


class TestTrend(unittest.TestCase):

    def test_uptrend(self):
        prices = [float(i) for i in range(1, 31)]
        t = calculate_trend(prices, window=20)
        self.assertGreater(t, 0)

    def test_downtrend(self):
        prices = [float(30 - i) for i in range(30)]
        t = calculate_trend(prices, window=20)
        self.assertLess(t, 0)

    def test_flat(self):
        prices = [100.0] * 20
        t = calculate_trend(prices, window=10)
        self.assertTrue(math.isclose(t, 0.0, abs_tol=1e-9))

    def test_empty(self):
        self.assertEqual(calculate_trend([], window=5), 0.0)

    def test_finite_result_with_nan(self):
        prices = [100.0, float("nan"), 102.0, 104.0, 106.0, 108.0]
        t = calculate_trend(prices, window=4)
        self.assertTrue(math.isfinite(t))


class TestVolumeRatio(unittest.TestCase):

    def test_spike(self):
        vols = [1000.0] * 20 + [5000.0]  # 5x spike
        r = calculate_volume_ratio(vols, window=20)
        self.assertAlmostEqual(r, 5.0, places=1)

    def test_zero_history(self):
        vols = [0.0] * 20 + [100.0]
        r = calculate_volume_ratio(vols, window=20)
        self.assertEqual(r, 1.0)  # neutral fallback

    def test_single_value(self):
        r = calculate_volume_ratio([1000.0], window=5)
        self.assertEqual(r, 1.0)


class TestSupportResistance(unittest.TestCase):

    def test_support_is_minimum(self):
        lows = [10.0, 5.0, 8.0, 12.0, 7.0]
        self.assertEqual(calculate_support(lows), 5.0)

    def test_resistance_is_maximum(self):
        highs = [10.0, 15.0, 8.0, 12.0, 7.0]
        self.assertEqual(calculate_resistance(highs), 15.0)

    def test_empty(self):
        self.assertEqual(calculate_support([]), 0.0)
        self.assertEqual(calculate_resistance([]), 0.0)

    def test_nan_filtered(self):
        lows = [10.0, float("nan"), 8.0]
        s = calculate_support(lows)
        self.assertTrue(math.isfinite(s))


class TestMarketResearchAnalyse(unittest.TestCase):

    def test_normal_data(self):
        prices = [float(100 + i) for i in range(60)]
        df = _make_df(prices)
        mr = MarketResearch()
        result = mr.analyse(df)
        for key in ("volatility", "momentum", "trend", "volume_ratio", "support", "resistance"):
            self.assertIn(key, result)
            self.assertTrue(math.isfinite(result[key]), f"{key} is not finite")

    def test_all_keys_returned(self):
        df = _make_df([100.0] * 30)
        result = MarketResearch().analyse(df)
        self.assertEqual(
            set(result.keys()),
            {"volatility", "momentum", "trend", "volume_ratio", "support", "resistance"},
        )

    def test_result_ordering(self):
        prices = [float(100 + i) for i in range(30)]
        df = _make_df(prices)
        result = MarketResearch().analyse(df)
        self.assertLessEqual(result["support"], result["resistance"])

    def test_empty_df(self):
        df = _make_df([])
        result = MarketResearch().analyse(df)
        for v in result.values():
            self.assertTrue(math.isfinite(v))

    def test_nan_in_closes(self):
        prices = [100.0, float("nan"), 102.0, float("nan"), 104.0] * 6
        df = _make_df(prices)
        result = MarketResearch().analyse(df)
        for v in result.values():
            self.assertTrue(math.isfinite(v), f"got {v}")

    def test_falling_data(self):
        prices = [float(100 - i) for i in range(30)]
        df = _make_df(prices)
        result = MarketResearch().analyse(df)
        self.assertLess(result["trend"], 0)

    def test_rising_data(self):
        prices = [float(100 + i) for i in range(30)]
        df = _make_df(prices)
        result = MarketResearch().analyse(df)
        self.assertGreater(result["trend"], 0)

    def test_custom_windows(self):
        prices = [float(100 + i) for i in range(60)]
        df = _make_df(prices)
        mr = MarketResearch(volatility_window=10, trend_window=15, sr_lookback=20)
        result = mr.analyse(df)
        self.assertTrue(all(math.isfinite(v) for v in result.values()))


if __name__ == "__main__":
    unittest.main()
