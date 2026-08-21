"""
tests/test_trade_store.py – TradeStore persistence tests.
"""
import os
import tempfile
import unittest
from datetime import timezone, datetime

from trade_store import TradeStore


class TestTradeStore(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.store = TradeStore(self._tmp.name)

    def tearDown(self):
        os.unlink(self._tmp.name)

    # ------------------------------------------------------------------
    # open / close
    # ------------------------------------------------------------------

    def test_open_and_close_trade(self):
        self.store.open_trade(
            symbol="AAPL",
            client_order_id="coid-1",
            entry_side="buy",
            entry_price=150.0,
            entry_qty=3,
            stop_loss=142.5,
            take_profit=172.5,
        )
        pnl = self.store.close_trade(
            client_order_id="coid-1",
            exit_price=160.0,
            exit_qty=3,
            exit_reason="take_profit",
        )
        self.assertAlmostEqual(pnl, 30.0)

    def test_open_trade_returns_id(self):
        row_id = self.store.open_trade(
            symbol="MSFT",
            client_order_id="coid-msft",
            entry_side="buy",
            entry_price=300.0,
            entry_qty=2,
        )
        self.assertIsInstance(row_id, int)
        self.assertGreater(row_id, 0)

    def test_closed_trade_not_in_open_positions(self):
        self.store.open_trade("AAPL", "coid-2", "buy", 150.0, 1)
        self.store.close_trade("coid-2", 155.0, 1)
        positions = self.store.get_open_positions()
        ids = [p["client_order_id"] for p in positions]
        self.assertNotIn("coid-2", ids)

    def test_open_position_in_open_positions(self):
        self.store.open_trade("AAPL", "coid-3", "buy", 150.0, 1)
        positions = self.store.get_open_positions()
        ids = [p["client_order_id"] for p in positions]
        self.assertIn("coid-3", ids)

    def test_entry_side_preserved_after_close(self):
        self.store.open_trade("AAPL", "coid-4", "buy", 150.0, 2)
        self.store.close_trade("coid-4", 160.0, 2, exit_side="sell")
        trade = self.store.get_trade("coid-4")
        self.assertEqual(trade["entry_side"], "buy")
        self.assertEqual(trade["exit_side"], "sell")

    def test_pnl_uses_entry_exit_prices(self):
        self.store.open_trade("AAPL", "coid-5", "buy", 100.0, 10)
        pnl = self.store.close_trade("coid-5", 110.0, 10)
        self.assertAlmostEqual(pnl, 100.0)  # (110-100)*10

    def test_missing_trade_raises(self):
        with self.assertRaises(ValueError):
            self.store.close_trade("nonexistent", 100.0, 1)

    # ------------------------------------------------------------------
    # intent status
    # ------------------------------------------------------------------

    def test_set_intent_status(self):
        self.store.open_trade("TSLA", "coid-6", "buy", 200.0, 1)
        self.store.set_intent_status("coid-6", "filled", broker_order_id="broker-42")
        trade = self.store.get_trade("coid-6")
        self.assertEqual(trade["intent_status"], "filled")
        self.assertEqual(trade["broker_order_id"], "broker-42")

    def test_mark_terminal(self):
        self.store.open_trade("TSLA", "coid-7", "buy", 200.0, 1)
        self.store.mark_terminal("coid-7", "canceled", broker_status="canceled")
        trade = self.store.get_trade("coid-7")
        self.assertEqual(trade["status"], "terminal")

    # ------------------------------------------------------------------
    # pending intents
    # ------------------------------------------------------------------

    def test_get_pending_intents(self):
        self.store.open_trade("AAPL", "pending-1", "buy", 150.0, 1)
        self.store.open_trade("AAPL", "pending-2", "buy", 151.0, 1)
        # close one
        self.store.close_trade("pending-2", 155.0, 1)
        intents = self.store.get_pending_intents()
        ids = [i["client_order_id"] for i in intents]
        self.assertIn("pending-1", ids)
        self.assertNotIn("pending-2", ids)

    def test_submitted_intent_appears(self):
        self.store.open_trade("AAPL", "sub-1", "buy", 150.0, 1)
        self.store.set_intent_status("sub-1", "submitted")
        intents = self.store.get_pending_intents()
        ids = [i["client_order_id"] for i in intents]
        self.assertIn("sub-1", ids)

    # ------------------------------------------------------------------
    # signals
    # ------------------------------------------------------------------

    def test_register_signal_first_time(self):
        ok = self.store.register_signal("AAPL", "gold_mine_0.80", 0.80)
        self.assertTrue(ok)

    def test_register_signal_duplicate_blocked(self):
        self.store.register_signal("AAPL", "gold_mine_0.80", 0.80)
        ok = self.store.register_signal("AAPL", "gold_mine_0.80", 0.80)
        self.assertFalse(ok)

    def test_has_recent_signal_true(self):
        self.store.register_signal("MSFT", "key1", 0.75)
        self.assertTrue(self.store.has_recent_signal("MSFT", "key1"))

    def test_has_recent_signal_false(self):
        self.assertFalse(self.store.has_recent_signal("MSFT", "nonexistent_key"))

    # ------------------------------------------------------------------
    # performance summary
    # ------------------------------------------------------------------

    def test_performance_summary(self):
        self.store.open_trade("AAPL", "ps-1", "buy", 100.0, 2)
        self.store.close_trade("ps-1", 110.0, 2)  # pnl=20
        self.store.open_trade("AAPL", "ps-2", "buy", 100.0, 2)
        self.store.close_trade("ps-2", 90.0, 2)   # pnl=-20
        s = self.store.performance_summary()
        self.assertEqual(s["total_trades"], 2)
        self.assertEqual(s["winning_trades"], 1)
        self.assertAlmostEqual(s["total_pnl"], 0.0)
        self.assertAlmostEqual(s["win_rate"], 0.5)

    def test_performance_summary_empty(self):
        s = self.store.performance_summary()
        self.assertEqual(s["total_trades"], 0)
        self.assertEqual(s["win_rate"], 0.0)

    # ------------------------------------------------------------------
    # recent trades
    # ------------------------------------------------------------------

    def test_get_recent_trades_ordered(self):
        for i in range(5):
            self.store.open_trade("AAPL", f"rt-{i}", "buy", 100.0 + i, 1)
            self.store.close_trade(f"rt-{i}", 105.0 + i, 1)
        trades = self.store.get_recent_trades(3)
        self.assertEqual(len(trades), 3)


if __name__ == "__main__":
    unittest.main()
