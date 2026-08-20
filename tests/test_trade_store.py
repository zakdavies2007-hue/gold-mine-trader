import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from trade_store import TradeStore


class TradeStoreTests(unittest.TestCase):
    def test_performance_summary_tracks_closed_trades(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        store = TradeStore(f'{tmpdir.name}/trading.db')
        trade_id = store.open_trade(
            symbol='AAPL',
            quantity=2,
            entry_price=100,
            stop_loss=95,
            take_profit=110,
            client_order_id='id-1',
            gold_mine_score=0.8,
        )
        closed = store.close_trade(trade_id, exit_price=105, closed_at=datetime.now(timezone.utc).isoformat())
        self.assertAlmostEqual(closed['pnl'], 10.0)
        summary = store.performance_summary(datetime.now(timezone.utc) + timedelta(hours=1))
        self.assertEqual(summary['open_positions'], 0)
        self.assertAlmostEqual(summary['daily_pnl'], 10.0)


if __name__ == '__main__':
    unittest.main()
