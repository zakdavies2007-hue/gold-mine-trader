"""
tests/test_trading_config.py – TradingConfig validation tests.
"""
import os
import unittest

from trading_config import TradingConfig, _coerce_time


def _base(**overrides):
    defaults = dict(
        stocks=["AAPL"],
        primary_stock="AAPL",
        threshold=0.75,
        scan_interval=30,
        starting_capital=500.0,
        risk_per_trade=0.10,
        stop_loss_percent=0.05,
        take_profit_percent=0.15,
        max_position_size=0.20,
        max_active_positions=5,
        position_hold_time=86400,
        alpaca_api_key="",
        alpaca_secret_key="",
        alpaca_base_url="https://paper-api.alpaca.markets",
        dry_run=True,
        max_daily_loss_percent=0.05,
    )
    defaults.update(overrides)
    return defaults


class TestTradingConfigValidation(unittest.TestCase):

    def test_valid_config_constructs(self):
        TradingConfig(**_base())

    def test_empty_stocks_raises(self):
        with self.assertRaises(ValueError):
            TradingConfig(**_base(stocks=[]))

    def test_primary_not_in_stocks_raises(self):
        with self.assertRaises(ValueError):
            TradingConfig(**_base(primary_stock="TSLA"))

    def test_stop_loss_zero_raises(self):
        with self.assertRaises(ValueError):
            TradingConfig(**_base(stop_loss_percent=0.0))

    def test_stop_loss_gt_1_raises(self):
        with self.assertRaises(ValueError):
            TradingConfig(**_base(stop_loss_percent=1.1))

    def test_negative_daily_loss_raises(self):
        with self.assertRaises(ValueError):
            TradingConfig(**_base(max_daily_loss_percent=-0.05))

    def test_daily_loss_as_fraction(self):
        cfg = TradingConfig(**_base(max_daily_loss_percent=0.20))
        self.assertAlmostEqual(cfg.max_daily_loss_percent, 0.20)

    def test_negative_scan_interval_raises(self):
        with self.assertRaises(ValueError):
            TradingConfig(**_base(scan_interval=-1))

    def test_market_close_before_open_raises(self):
        with self.assertRaises(ValueError):
            TradingConfig(**_base(market_open=16.0, market_close=9.5))

    def test_invalid_trading_day_raises(self):
        with self.assertRaises(ValueError):
            TradingConfig(**_base(trading_days=[0, 7]))

    def test_default_dry_run(self):
        cfg = TradingConfig(**_base())
        self.assertTrue(cfg.dry_run)

    def test_repr(self):
        cfg = TradingConfig(**_base())
        self.assertIn("TradingConfig", repr(cfg))


class TestCoerceTime(unittest.TestCase):

    def test_float_passthrough(self):
        self.assertAlmostEqual(_coerce_time(9.5), 9.5)

    def test_string_colon(self):
        self.assertAlmostEqual(_coerce_time("09:30"), 9.5)

    def test_invalid_minutes(self):
        with self.assertRaises(ValueError):
            _coerce_time("09:60")


class TestFromEnv(unittest.TestCase):

    def test_from_env_default_dry_run(self):
        """from_env should produce a valid config without a .env file."""
        # Remove any ALPACA keys from env to avoid validation issues
        env_backup = {k: os.environ.pop(k) for k in [
            "STOCKS", "PRIMARY_STOCK", "DRY_RUN", "MAX_DAILY_LOSS_PERCENT",
            "ALPACA_BASE_URL",
        ] if k in os.environ}
        try:
            cfg = TradingConfig.from_env()
            self.assertTrue(cfg.dry_run)
            self.assertGreater(cfg.max_daily_loss_percent, 0)
        finally:
            os.environ.update(env_backup)


if __name__ == "__main__":
    unittest.main()
