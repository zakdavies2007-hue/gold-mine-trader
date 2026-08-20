import unittest

from alpaca_broker import AlpacaBroker, BrokerGuardrailError
from trading_config import LIVE_TRADING_ACK, TradingConfig


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError('Network call was not expected in this test.')


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
        'position_hold_time': 86400,
        'max_daily_loss_percent': 0.05,
        'market_timezone': 'UTC',
        'market_open': '09:30',
        'market_close': '16:00',
        'trading_days': (0, 1, 2, 3, 4),
        'trading_mode': 'paper',
        'dry_run': False,
        'enable_live_trading': False,
        'live_trading_acknowledgement': '',
        'alpaca_api_key': 'key',
        'alpaca_secret_key': 'secret',
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


class BrokerGuardrailTests(unittest.TestCase):
    def test_paper_mode_requires_exact_paper_hostname(self):
        broker = AlpacaBroker(make_config(alpaca_base_url='https://api.alpaca.markets'), session=FakeSession())
        with self.assertRaisesRegex(BrokerGuardrailError, 'paper-api.alpaca.markets'):
            broker.validate_mode()

    def test_lookalike_url_path_injection_rejected(self):
        broker = AlpacaBroker(make_config(alpaca_base_url='https://example.com/paper-api.alpaca.markets'), session=FakeSession())
        with self.assertRaisesRegex(BrokerGuardrailError, 'hostname'):
            broker.validate_mode()

    def test_lookalike_subdomain_rejected(self):
        broker = AlpacaBroker(make_config(alpaca_base_url='https://paper-api.alpaca.markets.evil.test'), session=FakeSession())
        with self.assertRaisesRegex(BrokerGuardrailError, 'hostname'):
            broker.validate_mode()

    def test_non_https_rejected(self):
        broker = AlpacaBroker(make_config(alpaca_base_url='http://paper-api.alpaca.markets'), session=FakeSession())
        with self.assertRaisesRegex(BrokerGuardrailError, 'HTTPS'):
            broker.validate_mode()

    def test_embedded_credentials_rejected(self):
        broker = AlpacaBroker(make_config(alpaca_base_url='https://user@paper-api.alpaca.markets'), session=FakeSession())
        with self.assertRaisesRegex(BrokerGuardrailError, 'embedded credentials'):
            broker.validate_mode()

    def test_live_mode_requires_live_hostname(self):
        broker = AlpacaBroker(
            make_config(
                trading_mode='live',
                enable_live_trading=True,
                live_trading_acknowledgement=LIVE_TRADING_ACK,
                alpaca_base_url='https://paper-api.alpaca.markets',
            ),
            session=FakeSession(),
        )
        with self.assertRaisesRegex(BrokerGuardrailError, 'api.alpaca.markets'):
            broker.validate_mode()

    def test_invalid_order_side_rejected(self):
        broker = AlpacaBroker(make_config(dry_run=True), session=FakeSession())
        with self.assertRaisesRegex(BrokerGuardrailError, 'Order side'):
            broker.submit_order(symbol='AAPL', qty=1, side='hold', client_order_id='c1')

    def test_dry_run_order_does_not_need_credentials(self):
        session = FakeSession()
        broker = AlpacaBroker(make_config(dry_run=True, alpaca_api_key='', alpaca_secret_key=''), session=session)
        result = broker.submit_order(symbol='AAPL', qty=1, side='buy', client_order_id='c1')
        self.assertEqual(result['mode'], 'dry_run')
        self.assertEqual(session.calls, [])

    def test_live_trading_requires_acknowledgement(self):
        broker = AlpacaBroker(
            make_config(
                trading_mode='live',
                enable_live_trading=True,
                live_trading_acknowledgement='WRONG',
                alpaca_base_url='https://api.alpaca.markets',
            ),
            session=FakeSession(),
        )
        with self.assertRaisesRegex(BrokerGuardrailError, 'acknowledgement'):
            broker.validate_mode()
