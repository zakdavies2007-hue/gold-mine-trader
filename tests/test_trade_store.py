import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trade_store import TradeStore


class TradeStoreTests(unittest.TestCase):
    def test_performance_summary_tracks_closed_trades(self):
        store = TradeStore(':memory:')
        trade_id = store.open_trade(
            symbol='AAPL',
            quantity=2,
            entry_price=10.0,
            stop_loss=9.0,
            take_profit=11.0,
            client_order_id='c1',
            broker_order_id='b1',
            gold_mine_score=0.8,
        )
        closed_at = datetime.now(timezone.utc).isoformat()
        store.close_trade(trade_id, 12.5, closed_at=closed_at)
        summary = store.performance_summary(now=datetime.now(timezone.utc))
        self.assertEqual(summary['open_positions'], 0)
        self.assertAlmostEqual(summary['daily_pnl'], 5.0)
        self.assertAlmostEqual(summary['weekly_pnl'], 5.0)
        self.assertAlmostEqual(summary['monthly_pnl'], 5.0)

    def test_signal_can_recur_after_cooldown(self):
        store = TradeStore(':memory:')
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        store.register_signal('AAPL', 'sig', created_at=old_time)
        self.assertFalse(store.has_recent_signal('AAPL', 'sig', cooldown_seconds=30))
        store.register_signal('AAPL', 'sig')
        self.assertTrue(store.has_recent_signal('AAPL', 'sig', cooldown_seconds=30))
        with store.connect() as connection:
            row = connection.execute(
                'SELECT COUNT(*) AS count FROM signals WHERE symbol = ? AND signal_key = ?',
                ('AAPL', 'sig'),
            ).fetchone()
        self.assertEqual(row['count'], 2)

    def test_order_intent_idempotency(self):
        store = TradeStore(':memory:')
        self.assertTrue(store.persist_order_intent(client_order_id='c1', symbol='AAPL', side='buy', quantity=1))
        self.assertFalse(store.persist_order_intent(client_order_id='c1', symbol='AAPL', side='buy', quantity=1))

    def test_get_recent_trades_invalid_limit(self):
        store = TradeStore(':memory:')
        with self.assertRaisesRegex(ValueError, 'limit'):
            store.get_recent_trades(0)

    def test_memory_store_shared_connection(self):
        store = TradeStore(':memory:')
        store.record_scan({'symbol': 'AAPL', 'timestamp': datetime.now(timezone.utc).isoformat(), 'payload': 'x'})
        with store.connect() as connection:
            row = connection.execute('SELECT COUNT(*) AS count FROM scans').fetchone()
        self.assertEqual(row['count'], 1)
        self.assertEqual(len(store.get_recent_trades()), 0)

    def test_parent_directories_created(self):
        base = Path('tests_runtime_artifacts')
        db_path = base / 'nested' / 'dir' / 'trading.db'
        if base.exists():
            shutil.rmtree(base)
        store = TradeStore(str(db_path))
        self.assertTrue(db_path.parent.exists())
        with store.connect() as connection:
            connection.execute('SELECT 1')
        shutil.rmtree(base)
