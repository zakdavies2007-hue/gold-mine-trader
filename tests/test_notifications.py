import smtplib
import unittest
from unittest.mock import patch

import requests

from notifications import NotificationManager
from trading_config import TradingConfig


class ErrorResponse:
    status_code = 500

    def raise_for_status(self):
        raise requests.HTTPError('boom')


class FakeSession:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.response is None:
            raise AssertionError('HTTP call was not expected.')
        return self.response


class ExplodingSMTP:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        raise smtplib.SMTPException('smtp failure')


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


class NotificationManagerTests(unittest.TestCase):
    def test_discord_http_error_logged_not_raised(self):
        manager = NotificationManager(
            make_config(discord_webhook='https://discord.example/webhook'),
            session=FakeSession(response=ErrorResponse()),
        )
        with self.assertLogs('notifications', level='WARNING') as logs:
            manager.send('subject', 'message')
        self.assertTrue(any('Discord notification HTTP error' in line for line in logs.output))

    def test_telegram_no_token_skips_silently(self):
        session = FakeSession()
        manager = NotificationManager(make_config(), session=session)
        manager.send('subject', 'message')
        self.assertEqual(session.calls, [])

    def test_email_smtp_exception_logged_not_raised(self):
        manager = NotificationManager(
            make_config(email_alerts=True, email_address='user@example.com', email_password='secret'),
            session=FakeSession(),
        )
        with patch('smtplib.SMTP', ExplodingSMTP):
            with self.assertLogs('notifications', level='WARNING') as logs:
                manager.send('subject', 'message')
        self.assertTrue(any('Email SMTP error' in line for line in logs.output))
