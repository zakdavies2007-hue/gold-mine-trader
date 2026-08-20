import unittest

from alpaca_broker import AlpacaBroker, BrokerGuardrailError
from trading_config import LIVE_TRADING_ACK, TradingConfig


class BrokerGuardrailTests(unittest.TestCase):
    def test_default_dry_run_order_does_not_need_credentials(self):
        config = TradingConfig.from_env()
        broker = AlpacaBroker(config)
        order = broker.submit_order(symbol='AAPL', qty=1, side='buy', client_order_id='abc')
        self.assertEqual(order['mode'], 'dry_run')

    def test_live_trading_requires_explicit_acknowledgement(self):
        config = TradingConfig(
            stocks=('AAPL',),
            primary_stock='AAPL',
            gold_mine_threshold=0.75,
            scan_interval=30,
            starting_capital=500,
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
            trading_mode='live',
            dry_run=False,
            enable_live_trading=True,
            live_trading_acknowledgement='',
            alpaca_api_key='key',
            alpaca_secret_key='secret',
            alpaca_base_url='https://api.alpaca.markets',
            database_path=':memory:',
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
        broker = AlpacaBroker(config)
        with self.assertRaises(BrokerGuardrailError):
            broker.validate_mode()
        live_config = config.__class__(**{**config.__dict__, 'live_trading_acknowledgement': LIVE_TRADING_ACK})
        AlpacaBroker(live_config).validate_mode()


if __name__ == '__main__':
    unittest.main()
