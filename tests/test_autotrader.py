import unittest
from datetime import datetime, timezone

from autotrader import AutoTrader, MarketClock
from position_manager import PositionManager
from trade_store import TradeStore
from trading_config import TradingConfig


class FakeILoc:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, index):
        return self.values[index]


class FakeSeries:
    def __init__(self, values):
        self.iloc = FakeILoc(values)


class FakePriceData:
    def __init__(self, close_values):
        self.empty = False
        self._close_values = close_values

    def __getitem__(self, key):
        if key != 'Close':
            raise KeyError(key)
        return FakeSeries(self._close_values)


class FakeDetector:
    def __init__(self, scan_result=None, price_lookup=None):
        self.scan_result = scan_result or {
            'symbol': 'AAPL',
            'gold_mine_score': 0.9,
            'is_gold_mine': True,
            'price': 10.0,
            'research': {},
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        self.price_lookup = price_lookup or {'AAPL': 10.0}

    def scan_multiple_stocks(self, symbols):
        result = dict(self.scan_result)
        return {symbol: {**result, 'symbol': symbol} for symbol in symbols}

    def get_price_data(self, symbol):
        price = self.price_lookup.get(symbol)
        if price is None:
            return None
        return FakePriceData([price])


class FakeBroker:
    def __init__(self):
        self.orders = []

    def get_account(self):
        return {'equity': '1000', 'status': 'ACTIVE'}

    def submit_order(self, *, symbol, qty, side, client_order_id):
        order = {
            'id': f'broker-{client_order_id}',
            'symbol': symbol,
            'qty': str(qty),
            'side': side,
            'client_order_id': client_order_id,
            'status': 'accepted',
        }
        self.orders.append(order)
        return order

    def get_order_by_client_id(self, client_order_id):
        for order in self.orders:
            if order['client_order_id'] == client_order_id:
                return order
        return None


class FakeNotifier:
    def __init__(self):
        self.alerts = []

    def send_trade_alert(self, trade):
        self.alerts.append(trade)


class FailingTradeStore(TradeStore):
    def open_trade(self, *args, **kwargs):
        raise RuntimeError('db write failed')


def make_config(**overrides):
    defaults = {
        'stocks': ('AAPL',),
        'primary_stock': 'AAPL',
        'gold_mine_threshold': 0.75,
        'scan_interval': 30,
        'starting_capital': 500.0,
        'risk_per_trade': 0.10,
        'stop_loss_percent': 0.05,
        'take_profit_percent': 0.15,
        'max_position_size': 0.20,
        'max_active_positions': 5,
        'position_hold_time': 3600,
        'max_daily_loss_percent': 0.05,
        'market_timezone': 'UTC',
        'market_open': '09:30',
        'market_close': '16:00',
        'trading_days': (0, 1, 2, 3, 4),
        'trading_mode': 'paper',
        'dry_run': True,
        'enable_live_trading': False,
        'live_trading_acknowledgement': '',
        'alpaca_api_key': '',
        'alpaca_secret_key': '',
        'alpaca_base_url': 'https://paper-api.alpaca.markets',
        'database_path': ':memory:',
        'dashboard_host': '127.0.0.1',
        'dashboard_port': 8000,
        'dashboard_public_base_url': '',
        'discord_webhook': '',
        'telegram_token': '',
        'telegram_chat_id': '',
        'email_alerts': False,
        'email_address': '',
        'email_password': '',
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587,
    }
    defaults.update(overrides)
    return TradingConfig(**defaults)


def build_trader(store=None, detector=None, broker=None, notifier=None, config=None, clock=None):
    config = config or make_config()
    store = store or TradeStore(':memory:')
    detector = detector or FakeDetector()
    broker = broker or FakeBroker()
    notifier = notifier or FakeNotifier()
    positions = PositionManager(config)
    clock = clock or MarketClock(config.market_timezone, config.market_open, config.market_close, config.trading_days)
    trader = AutoTrader(
        detector=detector,
        broker=broker,
        store=store,
        positions=positions,
        notifier=notifier,
        config=config,
        clock=clock,
    )
    return trader, store, broker, notifier


class AutoTraderTests(unittest.TestCase):
    def test_market_clock_respects_trading_days_and_hours(self):
        clock = MarketClock('UTC', '09:30', '16:00', (0, 1, 2, 3, 4))
        self.assertTrue(clock.is_market_open(datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)))
        self.assertFalse(clock.is_market_open(datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)))
        self.assertFalse(clock.is_market_open(datetime(2026, 8, 17, 16, 0, tzinfo=timezone.utc)))
        self.assertFalse(clock.is_market_open(datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)))

    def test_repeated_scans_do_not_duplicate_orders(self):
        now = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        trader, store, broker, notifier = build_trader()
        result_one = trader.scan_cycle(now=now)
        result_two = trader.scan_cycle(now=now)
        self.assertEqual(result_one['status'], 'ok')
        self.assertEqual(result_two['status'], 'ok')
        self.assertEqual(len(broker.orders), 1)
        self.assertEqual(len(result_one['executed']), 1)
        self.assertEqual(len(result_two['executed']), 0)
        self.assertEqual(len(store.get_open_positions()), 1)

    def test_manage_positions_runs_when_market_closed(self):
        store = TradeStore(':memory:')
        store.open_trade(
            symbol='AAPL',
            quantity=3,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            client_order_id='open-1',
            broker_order_id='broker-open-1',
            gold_mine_score=0.9,
        )
        detector = FakeDetector(price_lookup={'AAPL': 90.0})
        trader, store, broker, notifier = build_trader(store=store, detector=detector)
        closed_time = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
        result = trader.scan_cycle(now=closed_time)
        self.assertEqual(result['status'], 'market_closed')
        self.assertEqual(len(result['managed_positions']), 1)
        self.assertEqual(len(broker.orders), 1)
        self.assertEqual(broker.orders[0]['side'], 'sell')
        self.assertEqual(store.get_open_positions(), [])
        self.assertEqual(len(notifier.alerts), 1)
        self.assertEqual(notifier.alerts[0]['status'], 'closed')

    def test_db_failure_after_broker_order_preserved_as_pending_intent(self):
        now = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        store = FailingTradeStore(':memory:')
        trader, store, broker, notifier = build_trader(store=store)
        result = trader.scan_cycle(now=now)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['executed']), 0)
        self.assertEqual(len(broker.orders), 1)
        with store.connect() as connection:
            row = connection.execute(
                'SELECT status, broker_order_id FROM order_intents WHERE client_order_id = ?',
                (f'gmt-AAPL-{int(now.timestamp())}',),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['status'], 'submitted')
        self.assertTrue(row['broker_order_id'].startswith('broker-gmt-AAPL-'))
