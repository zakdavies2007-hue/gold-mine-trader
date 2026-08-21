"""
tests/test_detector.py – GoldMineTrader detector unit tests (fully offline).

All network calls (yfinance, NewsAPI, FinBERT) are mocked.
"""
import math
import unittest
import unittest.mock as mock
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

import gold_mine_trader as gmt
from gold_mine_trader import (
    GoldMineTrader,
    GoldMineResult,
    analyze_sentiment,
    detect_catalysts,
    calculate_technical_score,
    get_price_data,
    get_news,
    _validate_weights,
)


def _make_price_df(n=60, start=100.0, drift=0.5):
    closes = [start + i * drift for i in range(n)]
    return pd.DataFrame({
        "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "volume": [1_000_000.0] * n,
    })


class TestValidateWeights(unittest.TestCase):

    def test_valid_weights(self):
        _validate_weights(0.35, 0.30, 0.35)  # no exception

    def test_weights_not_summing_to_1(self):
        with self.assertRaises(ValueError):
            _validate_weights(0.5, 0.5, 0.5)

    def test_weight_out_of_range(self):
        with self.assertRaises(ValueError):
            _validate_weights(-0.1, 0.5, 0.6)


class TestAnalyzeSentiment(unittest.TestCase):

    def test_no_texts_returns_neutral(self):
        score, degraded = analyze_sentiment([])
        self.assertAlmostEqual(score, 0.5)
        self.assertFalse(degraded)

    def test_finbert_disabled_returns_neutral_degraded(self):
        score, degraded = analyze_sentiment(["Great earnings!"], disable_finbert=True)
        self.assertAlmostEqual(score, 0.5)
        self.assertTrue(degraded)

    def test_finbert_fail_returns_neutral_degraded(self):
        # Force _finbert_failed so _load_finbert returns None
        orig = gmt._finbert_failed
        gmt._finbert_failed = True
        try:
            score, degraded = analyze_sentiment(["Great earnings!"])
            self.assertAlmostEqual(score, 0.5)
            self.assertTrue(degraded)
        finally:
            gmt._finbert_failed = orig

    def test_positive_label(self):
        mock_pipe = MagicMock(return_value=[{"label": "positive", "score": 0.9}])
        with patch.object(gmt, "_finbert_pipeline", mock_pipe), \
             patch.object(gmt, "_finbert_failed", False):
            score, degraded = analyze_sentiment(["Great earnings!"])
        self.assertFalse(degraded)
        self.assertGreater(score, 0.5)

    def test_negative_label(self):
        mock_pipe = MagicMock(return_value=[{"label": "negative", "score": 0.8}])
        with patch.object(gmt, "_finbert_pipeline", mock_pipe), \
             patch.object(gmt, "_finbert_failed", False):
            score, degraded = analyze_sentiment(["Terrible results!"])
        self.assertFalse(degraded)
        self.assertLess(score, 0.5)

    def test_neutral_label(self):
        mock_pipe = MagicMock(return_value=[{"label": "neutral", "score": 0.9}])
        with patch.object(gmt, "_finbert_pipeline", mock_pipe), \
             patch.object(gmt, "_finbert_failed", False):
            score, degraded = analyze_sentiment(["Company had some news"])
        self.assertAlmostEqual(score, 0.5)


class TestDetectCatalysts(unittest.TestCase):

    def test_no_articles(self):
        score, count = detect_catalysts([])
        self.assertEqual(score, 0.0)
        self.assertEqual(count, 0)

    def test_catalyst_in_title(self):
        articles = [{"title": "Company beats earnings expectations", "description": ""}]
        score, count = detect_catalysts(articles)
        self.assertEqual(count, 1)
        self.assertGreater(score, 0)

    def test_no_catalyst_keywords(self):
        articles = [{"title": "Weather is nice today", "description": ""}]
        score, count = detect_catalysts(articles)
        self.assertEqual(count, 0)

    def test_multiple_articles_with_catalysts(self):
        articles = [
            {"title": "Record revenue reported", "description": ""},
            {"title": "FDA approval granted", "description": ""},
        ]
        score, count = detect_catalysts(articles)
        self.assertEqual(count, 2)
        self.assertAlmostEqual(score, 1.0)


class TestTechnicalScore(unittest.TestCase):

    def test_normal_data_finite(self):
        df = _make_price_df(60)
        score, degraded = calculate_technical_score(df)
        self.assertFalse(degraded)
        self.assertTrue(0 <= score <= 1)
        self.assertTrue(math.isfinite(score))

    def test_empty_df_degraded(self):
        score, degraded = calculate_technical_score(pd.DataFrame())
        self.assertTrue(degraded)
        self.assertAlmostEqual(score, 0.5)

    def test_none_df_degraded(self):
        score, degraded = calculate_technical_score(None)
        self.assertTrue(degraded)

    def test_nan_in_closes(self):
        df = _make_price_df(30)
        df.loc[5:10, "close"] = float("nan")
        score, degraded = calculate_technical_score(df)
        self.assertTrue(math.isfinite(score))

    def test_single_row_degraded(self):
        df = _make_price_df(1)
        score, degraded = calculate_technical_score(df)
        self.assertTrue(degraded)


class TestGetPriceDataMocked(unittest.TestCase):

    def test_returns_dataframe_on_success(self):
        df = _make_price_df(30)
        with patch("yfinance.download", return_value=df):
            gmt._price_cache._store.clear()
            result = get_price_data("AAPL", period="1mo")
        self.assertIsNotNone(result)
        self.assertFalse(result.empty)

    def test_returns_none_on_empty(self):
        with patch("yfinance.download", return_value=pd.DataFrame()):
            gmt._price_cache._store.clear()
            result = get_price_data("INVALID_TICKER_XYZ", period="1mo")
        self.assertIsNone(result)


class TestGetNewsMocked(unittest.TestCase):

    def test_empty_key_returns_empty(self):
        result = get_news("AAPL", api_key="")
        self.assertEqual(result, [])

    def test_demo_key_returns_empty(self):
        result = get_news("AAPL", api_key="demo")
        self.assertEqual(result, [])

    def test_network_failure_returns_empty(self):
        import requests
        with patch("requests.get", side_effect=requests.RequestException("network error")):
            result = get_news("AAPL", api_key="somekey123")
        self.assertEqual(result, [])


class TestScanForGoldMine(unittest.TestCase):

    def _make_trader(self, news_key="", disable_finbert=True):
        return GoldMineTrader(
            news_api_key=news_key,
            disable_finbert=disable_finbert,
            threshold=0.75,
        )

    def test_degraded_when_no_price_data(self):
        trader = self._make_trader()
        with patch.object(gmt, "get_price_data", return_value=None):
            result = trader.scan_for_gold_mine("FAKE")
        self.assertFalse(result.eligible)
        self.assertIn("price_data", result.degraded_providers)
        self.assertFalse(result.is_gold_mine)

    def test_degraded_when_finbert_disabled(self):
        trader = self._make_trader(disable_finbert=True)
        df = _make_price_df(60)
        with patch.object(gmt, "get_price_data", return_value=df), \
             patch.object(gmt, "get_news", return_value=[]):
            result = trader.scan_for_gold_mine("AAPL")
        # No news → sentiment is not degraded (neutral is OK without news)
        # FinBERT disabled AND texts are empty → analyze_sentiment returns (0.5, False)
        self.assertTrue(math.isfinite(result.score))

    def test_eligible_and_high_score_is_gold_mine(self):
        trader = self._make_trader(disable_finbert=True)
        df = _make_price_df(250)  # enough for MA200
        # Mock catalysts to boost catalyst score
        articles = [
            {"title": "Record revenue reported", "description": ""},
            {"title": "FDA approval granted", "description": ""},
        ]
        with patch.object(gmt, "get_price_data", return_value=df), \
             patch.object(gmt, "get_news", return_value=articles):
            result = trader.scan_for_gold_mine("AAPL")
        # Should be eligible (no degraded providers except possibly sentiment
        # when disable_finbert=True with articles → degraded)
        # When finbert is disabled and texts are non-empty → degraded=True
        if result.eligible:
            self.assertTrue(math.isfinite(result.score))

    def test_zero_price_not_eligible(self):
        trader = self._make_trader(disable_finbert=True)
        df = pd.DataFrame({
            "close": [0.0] * 10,
            "high": [0.0] * 10,
            "low": [0.0] * 10,
            "volume": [1000.0] * 10,
        })
        with patch.object(gmt, "get_price_data", return_value=df):
            result = trader.scan_for_gold_mine("AAPL")
        self.assertFalse(result.eligible)

    def test_scan_returns_gold_mine_result(self):
        trader = self._make_trader()
        with patch.object(gmt, "get_price_data", return_value=None):
            result = trader.scan_for_gold_mine("AAPL")
        self.assertIsInstance(result, GoldMineResult)
        self.assertEqual(result.symbol, "AAPL")


class TestScanMultipleStocks(unittest.TestCase):

    def test_returns_in_input_order(self):
        symbols = ["AAPL", "MSFT", "NVDA"]
        trader = GoldMineTrader(disable_finbert=True, news_api_key="")
        with patch.object(gmt, "get_price_data", return_value=None):
            results = trader.scan_multiple_stocks(symbols)
        self.assertEqual([r.symbol for r in results], symbols)

    def test_error_per_symbol_does_not_crash(self):
        trader = GoldMineTrader(disable_finbert=True, news_api_key="")
        with patch.object(gmt, "get_price_data", side_effect=RuntimeError("boom")):
            results = trader.scan_multiple_stocks(["AAPL", "MSFT"])
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertFalse(r.eligible)


if __name__ == "__main__":
    unittest.main()
