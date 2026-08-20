import os
import unittest
from unittest.mock import patch

from trading_config import TradingConfig


class TradingConfigTests(unittest.TestCase):
    def test_default_max_daily_loss_is_0_05(self):
        with patch.dict(os.environ, {}, clear=True):
            config = TradingConfig.from_env()
        self.assertEqual(config.max_daily_loss_percent, 0.05)

    def test_invalid_bool_raises_value_error(self):
        with patch.dict(os.environ, {'DRY_RUN': 'maybe'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'DRY_RUN'):
                TradingConfig.from_env()

    def test_empty_stocks_raises_value_error(self):
        with patch.dict(os.environ, {'STOCKS': ' , '}, clear=True):
            with self.assertRaisesRegex(ValueError, 'STOCKS'):
                TradingConfig.from_env()

    def test_primary_stock_not_in_stocks_raises_value_error(self):
        with patch.dict(os.environ, {'STOCKS': 'MSFT,NVDA', 'PRIMARY_STOCK': 'AAPL'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'PRIMARY_STOCK'):
                TradingConfig.from_env()

    def test_negative_scan_interval_raises_value_error(self):
        with patch.dict(os.environ, {'SCAN_INTERVAL': '-5'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'SCAN_INTERVAL'):
                TradingConfig.from_env()
