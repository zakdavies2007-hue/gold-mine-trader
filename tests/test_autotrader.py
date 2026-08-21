"""
tests/test_autotrader.py – Autotrader scan cycle and reconciliation tests.
"""
import os
import tempfile
import unittest
import unittest.mock as mock
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

from alpaca_broker import AlpacaBroker, BrokerGuardrailError
from autotrader import AutoTrader, MarketClock, _TERMINAL_STATUSES, _RECOVERABLE_STATUSES
from gold_mine_trader import GoldMineResult
from position_manager import PositionManager
from trade_store import TradeStore
from trading_config import TradingConfig


def _fake_config(**overrides):
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
        alpaca_api_key="key",
        alpaca_secret_key="secret",
        alpaca_base_url="https://paper-api.alpaca.markets",
        dry_run=True,
        max_daily_loss_percent=0.05,
        email_alerts=False,
        email_address="",
        email_password="",
        smtp_server="smtp.gmail.com",
        smtp_port=587,
        discord_webhook="",
        discord_alerts=False,
        telegram_token="",
        telegram_chat_id="",
        telegram_alerts=False,
        dashboard_host="127.0.0.1",
        dashboard_port=8000,
        database_path=":memory:",
        log_level="WARNING",
        max_workers=1,
        news_api_key="",
        disable_finbert=True,
        market_open=9.5,
        market_close=16.0,
        trading_days=[0, 1, 2, 3, 4],
    )
    defaults.update(overrides)
    return TradingConfig(**defaults)


def _make_autotrader(db_path=None, config_overrides=None):
    config = _fake_config(**(config_overrides or {}))
    if db_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_path = tmp.name
    store = TradeStore(db_path)
    broker = AlpacaBroker(
        api_key="key",
        secret_key="secret",
        base_url="https://paper-api.alpaca.markets",
        dry_run=True,
    )
    pm = PositionManager(
        stop_loss_pct=config.stop_loss_percent,
        take_profit_pct=config.take_profit_percent,
        max_hold_seconds=config.position_hold_time,
        capital=config.starting_capital,
        max_active_positions=config.max_active_positions,
        max_daily_loss_pct=config.max_daily_loss_percent,
    )
    detector = MagicMock()
    detector.scan_multiple_stocks.return_value = []
    at = AutoTrader(config=config, detector=detector, broker=broker,
                    trade_store=store, position_manager=pm)
    return at, store, db_path


class TestMarketClock(unittest.TestCase):

    def test_market_open_on_tuesday(self):
        # Tuesday 2026-08-20 14:00 UTC = 10:00 EDT
        now = datetime(2026, 8, 18, 14, 0, 0, tzinfo=timezone.utc)
        clock = MarketClock()
        self.assertTrue(clock.is_market_open(now))

    def test_market_closed_on_weekend(self):
        # Saturday 2026-08-22
        now = datetime(2026, 8, 22, 14, 0, 0, tzinfo=timezone.utc)
        clock = MarketClock()
        self.assertFalse(clock.is_market_open(now))

    def test_market_closed_after_hours(self):
        # Tuesday at 21:00 UTC = 17:00 EDT (after close)
        now = datetime(2026, 8, 18, 21, 0, 0, tzinfo=timezone.utc)
        clock = MarketClock()
        self.assertFalse(clock.is_market_open(now))

    def test_market_closed_before_open(self):
        # Tuesday at 12:00 UTC = 08:00 EDT (before open)
        now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)
        clock = MarketClock()
        self.assertFalse(clock.is_market_open(now))


class TestScanCycleNoSignals(unittest.TestCase):

    def setUp(self):
        self.at, self.store, self.db = _make_autotrader()

    def tearDown(self):
        os.unlink(self.db)

    def test_cycle_with_no_signals(self):
        with patch.object(self.at.clock, "is_market_open", return_value=True):
            result = self.at.scan_cycle()
        self.assertEqual(result["executions"], [])

    def test_cycle_market_closed_skips_scan(self):
        with patch.object(self.at.clock, "is_market_open", return_value=False):
            result = self.at.scan_cycle()
        self.at.detector.scan_multiple_stocks.assert_not_called()


class TestScanCycleExecution(unittest.TestCase):

    def setUp(self):
        self.at, self.store, self.db = _make_autotrader(
            config_overrides={"starting_capital": 10000.0}
        )

    def tearDown(self):
        os.unlink(self.db)

    def _gold_mine_result(self, symbol="AAPL", score=0.85, price=150.0):
        return GoldMineResult(
            symbol=symbol, is_gold_mine=True, score=score,
            eligible=True, degraded_providers=[],
            sentiment_score=0.8, catalyst_score=0.9, technical_score=0.8,
            catalyst_count=2, latest_price=price,
            timestamp="2026-08-20T14:00:00Z",
            metadata={},
        )

    def test_eligible_gold_mine_executed(self):
        self.at.detector.scan_multiple_stocks.return_value = [
            self._gold_mine_result()
        ]
        with patch.object(self.at.clock, "is_market_open", return_value=True):
            result = self.at.scan_cycle()
        self.assertEqual(len(result["executions"]), 1)
        self.assertEqual(result["executions"][0]["symbol"], "AAPL")

    def test_degraded_result_not_executed(self):
        degraded = GoldMineResult(
            symbol="AAPL", is_gold_mine=False, score=0.9,
            eligible=False, degraded_providers=["sentiment"],
            sentiment_score=0.5, catalyst_score=0.5, technical_score=0.5,
            catalyst_count=0, latest_price=150.0,
            timestamp="2026-08-20T14:00:00Z",
            metadata={},
        )
        self.at.detector.scan_multiple_stocks.return_value = [degraded]
        with patch.object(self.at.clock, "is_market_open", return_value=True):
            result = self.at.scan_cycle()
        self.assertEqual(result["executions"], [])
        skipped = [s["symbol"] for s in result["skipped"]]
        self.assertIn("AAPL", skipped)

    def test_zero_price_not_executed(self):
        res = self._gold_mine_result(price=0.0)
        self.at.detector.scan_multiple_stocks.return_value = [res]
        with patch.object(self.at.clock, "is_market_open", return_value=True):
            result = self.at.scan_cycle()
        self.assertEqual(result["executions"], [])

    def test_trade_recorded_in_store(self):
        self.at.detector.scan_multiple_stocks.return_value = [
            self._gold_mine_result()
        ]
        with patch.object(self.at.clock, "is_market_open", return_value=True):
            self.at.scan_cycle()
        # At least one intent should be recorded
        intents = self.store.get_pending_intents()
        # After successful dry-run submission, intent status may be 'accepted'
        # which is not in pending list – check open positions or all trades
        positions = self.store.get_open_positions()
        # Either pending or open
        all_count = len(intents) + len(positions)
        self.assertGreater(all_count, 0)

    def test_duplicate_signal_blocked(self):
        res = self._gold_mine_result(score=0.85)
        self.at.detector.scan_multiple_stocks.return_value = [res]
        with patch.object(self.at.clock, "is_market_open", return_value=True):
            self.at.scan_cycle()
            # Second cycle with same score
            result2 = self.at.scan_cycle()
        # Second execution should be blocked (duplicate signal)
        self.assertEqual(len(result2["executions"]), 0)


class TestReconciliation(unittest.TestCase):

    def setUp(self):
        self.at, self.store, self.db = _make_autotrader()

    def tearDown(self):
        os.unlink(self.db)

    def test_no_pending_intents_noop(self):
        n = self.at.reconcile_pending_intents()
        self.assertEqual(n, 0)

    def test_submitted_without_broker_order_marked_terminal(self):
        """Crash after intent=submitted but before broker order → terminal."""
        self.store.open_trade("AAPL", "crash-1", "buy", 150.0, 1)
        self.store.set_intent_status("crash-1", "submitted")
        # Broker returns None (no order found)
        with patch.object(self.at.broker, "get_order_by_client_id", return_value=None):
            self.at.reconcile_pending_intents()
        trade = self.store.get_trade("crash-1")
        self.assertEqual(trade["status"], "terminal")

    def test_pending_without_broker_order_left_alone(self):
        """Intent=pending (pre-submit) should not be marked terminal."""
        self.store.open_trade("AAPL", "pre-1", "buy", 150.0, 1)
        # intent_status remains 'pending' (default from open_trade is 'submitted')
        # override to pending
        with self.store._connect() as conn:
            conn.execute("UPDATE trades SET intent_status='pending' WHERE client_order_id='pre-1'")
        with patch.object(self.at.broker, "get_order_by_client_id", return_value=None):
            self.at.reconcile_pending_intents()
        trade = self.store.get_trade("pre-1")
        self.assertNotEqual(trade["status"], "terminal")

    def test_filled_broker_order_marks_open(self):
        self.store.open_trade("AAPL", "fill-1", "buy", 150.0, 1)
        self.store.set_intent_status("fill-1", "submitted")
        broker_order = {
            "id": "broker-abc", "status": "filled",
            "filled_avg_price": "151.50", "filled_qty": "1",
        }
        with patch.object(self.at.broker, "get_order_by_client_id", return_value=broker_order):
            self.at.reconcile_pending_intents()
        trade = self.store.get_trade("fill-1")
        self.assertEqual(trade["status"], "open")
        self.assertAlmostEqual(trade["entry_price"], 151.50)

    def test_canceled_broker_order_marks_terminal(self):
        self.store.open_trade("AAPL", "cancel-1", "buy", 150.0, 1)
        self.store.set_intent_status("cancel-1", "submitted")
        for status in ["canceled", "rejected", "expired"]:
            # Reset
            with self.store._connect() as conn:
                conn.execute("UPDATE trades SET status='open', intent_status='submitted' "
                             "WHERE client_order_id='cancel-1'")
            broker_order = {"id": "b-1", "status": status}
            with patch.object(self.at.broker, "get_order_by_client_id",
                               return_value=broker_order):
                self.at.reconcile_pending_intents()
            trade = self.store.get_trade("cancel-1")
            self.assertEqual(trade["status"], "terminal",
                             f"Expected terminal for broker status {status}")

    def test_recoverable_status_stays_submitted(self):
        self.store.open_trade("AAPL", "rec-1", "buy", 150.0, 1)
        self.store.set_intent_status("rec-1", "submitted")
        broker_order = {"id": "b-2", "status": "accepted"}
        with patch.object(self.at.broker, "get_order_by_client_id", return_value=broker_order):
            self.at.reconcile_pending_intents()
        trade = self.store.get_trade("rec-1")
        # Should NOT be terminal
        self.assertNotEqual(trade["status"], "terminal")


class TestPositionManagementOutsideHours(unittest.TestCase):

    def setUp(self):
        self.at, self.store, self.db = _make_autotrader(
            config_overrides={"stop_loss_percent": 0.05, "take_profit_percent": 0.10}
        )

    def tearDown(self):
        os.unlink(self.db)

    def test_exits_run_outside_market_hours(self):
        """Position management fires even when market is closed."""
        self.store.open_trade(
            symbol="AAPL",
            client_order_id="oom-1",
            entry_side="buy",
            entry_price=100.0,
            entry_qty=1,
        )
        # Simulate take-profit: price is 15% higher
        import pandas as pd
        fake_df = pd.DataFrame({
            "close": [115.0], "high": [115.5], "low": [114.5], "volume": [1000.0]
        })
        with patch("gold_mine_trader.get_price_data", return_value=fake_df), \
             patch.object(self.at.clock, "is_market_open", return_value=False):
            result = self.at.scan_cycle()
        # Exits should still occur even though market is closed
        self.assertEqual(len(result["exits"]), 1)
        self.assertEqual(result["exits"][0]["reason"], "take_profit")

    def test_weekend_exits_fire(self):
        """Same as above, but explicitly on a weekend datetime."""
        self.store.open_trade(
            symbol="AAPL",
            client_order_id="wknd-1",
            entry_side="buy",
            entry_price=100.0,
            entry_qty=1,
        )
        import pandas as pd
        fake_df = pd.DataFrame({
            "close": [94.0],  # stop-loss (-6%)
            "high": [95.0], "low": [93.5], "volume": [500.0]
        })
        saturday = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        clock = MarketClock()
        self.assertFalse(clock.is_market_open(saturday))

        with patch("gold_mine_trader.get_price_data", return_value=fake_df):
            exits = self.at.manage_positions()
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["reason"], "stop_loss")


if __name__ == "__main__":
    unittest.main()
