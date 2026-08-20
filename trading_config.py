from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Tuple

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - depends on optional dependency
    def load_dotenv():
        return False

load_dotenv()


LIVE_TRADING_ACK = 'I_UNDERSTAND_AND_ACCEPT_LIVE_TRADING_RISK'



def _import_config(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return None


_BASE = _import_config('config')
_ADVANCED = _import_config('config_advanced')



def _get_config_value(key: str, default):
    for module in (_ADVANCED, _BASE):
        if module and hasattr(module, key):
            return getattr(module, key)
    return default



def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}



def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, '') else float(default)



def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, '') else int(default)



def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, '') else default


def _coerce_time(value) -> str:
    if isinstance(value, (int, float)):
        hours = int(value)
        minutes = int(round((float(value) - hours) * 60))
        return f'{hours:02d}:{minutes:02d}'
    return str(value)


@dataclass(frozen=True)
class TradingConfig:
    stocks: Tuple[str, ...]
    primary_stock: str
    gold_mine_threshold: float
    scan_interval: int
    starting_capital: float
    risk_per_trade: float
    stop_loss_percent: float
    take_profit_percent: float
    max_position_size: float
    max_active_positions: int
    position_hold_time: int
    max_daily_loss_percent: float
    market_timezone: str
    market_open: str
    market_close: str
    trading_days: Tuple[int, ...]
    trading_mode: str
    dry_run: bool
    enable_live_trading: bool
    live_trading_acknowledgement: str
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_base_url: str
    database_path: str
    dashboard_host: str
    dashboard_port: int
    dashboard_public_base_url: str
    discord_webhook: str
    telegram_token: str
    telegram_chat_id: str
    email_alerts: bool
    email_address: str
    email_password: str
    smtp_server: str
    smtp_port: int

    @classmethod
    def from_env(cls) -> 'TradingConfig':
        stocks_value = _env_str('STOCKS', ','.join(_get_config_value('STOCKS', ['AAPL', 'MSFT', 'NVDA', 'TSLA'])))
        return cls(
            stocks=tuple(item.strip() for item in stocks_value.split(',') if item.strip()),
            primary_stock=_env_str('PRIMARY_STOCK', _get_config_value('PRIMARY_STOCK', 'AAPL')),
            gold_mine_threshold=_env_float('GOLD_MINE_THRESHOLD', _get_config_value('GOLD_MINE_THRESHOLD', 0.75)),
            scan_interval=_env_int('SCAN_INTERVAL', _get_config_value('SCAN_INTERVAL', 30)),
            starting_capital=_env_float('STARTING_CAPITAL', _get_config_value('STARTING_CAPITAL', _get_config_value('CAPITAL', 500))),
            risk_per_trade=_env_float('RISK_PER_TRADE', _get_config_value('RISK_PER_TRADE', 0.10)),
            stop_loss_percent=_env_float('STOP_LOSS_PERCENT', _get_config_value('STOP_LOSS_PERCENT', 0.05)),
            take_profit_percent=_env_float('TAKE_PROFIT_PERCENT', _get_config_value('TAKE_PROFIT_PERCENT', 0.15)),
            max_position_size=_env_float('MAX_POSITION_SIZE', _get_config_value('MAX_POSITION_SIZE', 0.20)),
            max_active_positions=_env_int('MAX_ACTIVE_POSITIONS', _get_config_value('MAX_ACTIVE_POSITIONS', 5)),
            position_hold_time=_env_int('POSITION_HOLD_TIME', _get_config_value('POSITION_HOLD_TIME', 86400)),
            max_daily_loss_percent=abs(_env_float('MAX_DAILY_LOSS_PERCENT', _get_config_value('MAX_DAILY_LOSS_PERCENT', 0.05))),
            market_timezone=_env_str('MARKET_TIMEZONE', _get_config_value('MARKET_TIMEZONE', 'America/New_York')),
            market_open=_env_str('MARKET_OPEN', _coerce_time(_get_config_value('MARKET_OPEN', '09:30'))),
            market_close=_env_str('MARKET_CLOSE', _coerce_time(_get_config_value('MARKET_CLOSE', '16:00'))),
            trading_days=tuple(int(day.strip()) for day in _env_str('TRADING_DAYS', ','.join(map(str, _get_config_value('TRADING_DAYS', [0, 1, 2, 3, 4])))).split(',') if day.strip()),
            trading_mode=_env_str('TRADING_MODE', 'paper').strip().lower(),
            dry_run=_env_bool('DRY_RUN', True),
            enable_live_trading=_env_bool('ENABLE_LIVE_TRADING', False),
            live_trading_acknowledgement=_env_str('LIVE_TRADING_ACKNOWLEDGEMENT', ''),
            alpaca_api_key=_env_str('ALPACA_API_KEY', _get_config_value('ALPACA_API_KEY', '')),
            alpaca_secret_key=_env_str('ALPACA_SECRET_KEY', _get_config_value('ALPACA_SECRET_KEY', '')),
            alpaca_base_url=_env_str('ALPACA_BASE_URL', _get_config_value('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')).rstrip('/'),
            database_path=_env_str('DATABASE_PATH', 'trading.db'),
            dashboard_host=_env_str('DASHBOARD_HOST', '127.0.0.1'),
            dashboard_port=_env_int('DASHBOARD_PORT', 8000),
            dashboard_public_base_url=_env_str('DASHBOARD_PUBLIC_BASE_URL', ''),
            discord_webhook=_env_str('DISCORD_WEBHOOK', _get_config_value('DISCORD_WEBHOOK', '')),
            telegram_token=_env_str('TELEGRAM_TOKEN', _get_config_value('TELEGRAM_TOKEN', '')),
            telegram_chat_id=_env_str('TELEGRAM_CHAT_ID', _get_config_value('TELEGRAM_CHAT_ID', '')),
            email_alerts=_env_bool('EMAIL_ALERTS', _get_config_value('EMAIL_ALERTS', False)),
            email_address=_env_str('EMAIL_ADDRESS', _get_config_value('EMAIL_ADDRESS', '')),
            email_password=_env_str('EMAIL_PASSWORD', _get_config_value('EMAIL_PASSWORD', '')),
            smtp_server=_env_str('SMTP_SERVER', _get_config_value('SMTP_SERVER', 'smtp.gmail.com')),
            smtp_port=_env_int('SMTP_PORT', _get_config_value('SMTP_PORT', 587)),
        )
