import tempfile
import unittest
from datetime import datetime, timezone

from autotrader import AutoTrader, MarketClock
from position_manager import PositionManager
from trade_store import TradeStore
from trading_config import TradingConfig


class FakeDetector:
    def __init__(self):
        self.scans = 0

    def scan_multiple_stocks(self, symbols):
        self.scans += 1
        return {
            'AAPL': {
                'symbol': 'AAPL',
                'gold_mine_score': 0.9,
                'sentiment': 0.8,
                'catalysts': 1,
                'technical': 0.8,
                'is_gold_mine': True,
                'price': 100.0,
                'research': {'volatility': 0.1},
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
        }

    def get_price_data(self, symbol):
        class EmptyData:
            empty = True

        return EmptyData()


class FakeBroker:
    def __init__(self):
        self.orders = []

    def get_account(self):
        return {'equity': '1000'}

    def submit_order(self, **kwargs):
        self.orders.append(kwargs)
        return {'id': str(len(self.orders)), **kwargs}


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send_trade_alert(self, trade):
        self.messages.append(trade)


class AutoTraderTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config = TradingConfig(
            stocks=('AAPL',),
            primary_stock='AAPL',
            gold_mine_threshold=0.75,
            scan_interval=30,
            starting_capital=1000,
            risk_per_trade=0.1,
            stop_loss_percent=0.05,
            take_profit_percent=0.15,
            max_position_size=0.2,
            max_active_positions=5,
            position_hold_time=86400,
            max_daily_loss_percent=0.05,
            market_timezone='America/New_York',
            market_open='09:30',
            market_close='16:00',
            trading_days=(0, 1, 2, 3, 4),
            trading_mode='paper',
            dry_run=True,
            enable_live_trading=False,
            live_trading_acknowledgement='',
            alpaca_api_key='',
            alpaca_secret_key='',
            alpaca_base_url='https://paper-api.alpaca.markets',
            database_path=f"{self.tmpdir.name}/trading.db",
            dashboard_host='127.0.0.1',
            dashboard_port=8000,
            dashboard_public_base_url='',
            discord_webhook='',
            telegram_token='',
            telegram_chat_id='',
            email_alerts=False,
            email_address='',
            email_password='',
            smtp_server='smtp.gmail.com',
            smtp_port=587,
        )

    def test_market_clock_respects_trading_days_and_hours(self):
        clock = MarketClock('America/New_York', '09:30', '16:00', (0, 1, 2, 3, 4))
        self.assertTrue(clock.is_market_open(datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)))
        self.assertFalse(clock.is_market_open(datetime(2026, 8, 22, 14, 0, tzinfo=timezone.utc)))
        self.assertFalse(clock.is_market_open(datetime(2026, 8, 20, 22, 0, tzinfo=timezone.utc)))

    def test_repeated_scans_do_not_duplicate_orders(self):
        store = TradeStore(self.config.database_path)
        trader = AutoTrader(
            detector=FakeDetector(),
            broker=FakeBroker(),
            store=store,
            positions=PositionManager(self.config),
            notifier=FakeNotifier(),
            config=self.config,
            clock=MarketClock('America/New_York', '09:30', '16:00', (0, 1, 2, 3, 4)),
        )
        now = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)
        first = trader.scan_cycle(now=now)
        second = trader.scan_cycle(now=now)
        self.assertEqual(len(first['executed']), 1)
        self.assertEqual(len(second['executed']), 0)
        self.assertEqual(len(store.get_open_positions()), 1)


if __name__ == '__main__':
    unittest.main()
