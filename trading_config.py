"""
trading_config.py – Centralised, validated configuration for Gold Mine Trader.

All settings are driven by environment variables (loaded from .env if present).
Legacy values from config_advanced.py are used as fallbacks where the env var
is absent and the legacy module is importable; this keeps notebook compatibility.
"""

from __future__ import annotations

import math
import os

try:
    from dotenv import load_dotenv as _dotenv_load
except ImportError:  # pragma: no cover
    def _dotenv_load(**_kw):  # type: ignore[misc]
        pass

_dotenv_load()


def _legacy(attr: str, default):
    """Return a value from config_advanced.py or *default* if unavailable."""
    try:
        import config_advanced as _ca  # type: ignore[import]
        return getattr(_ca, attr, default)
    except Exception:
        return default


def _env_str(key: str, fallback=None) -> str | None:
    return os.environ.get(key) or fallback


def _env_bool(key: str, fallback: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return fallback
    return raw.strip().lower() in ("1", "true", "yes")


def _env_int(key: str, fallback: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return fallback
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {key}={raw!r} is not a valid integer") from exc


def _env_float(key: str, fallback: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return fallback
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {key}={raw!r} is not a valid float") from exc


def _coerce_time(raw) -> float:
    """Accept 9.5 or '09:30' and return a float hour."""
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if ":" in s:
        parts = s.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if m >= 60:
            raise ValueError(f"Invalid time value {raw!r}: minutes must be < 60")
        return h + m / 60.0
    return float(s)


class TradingConfig:
    """Validated configuration object.

    Construct via :meth:`from_env` rather than directly.
    """

    def __init__(self, **kw):
        # Core
        self.stocks: list[str] = kw["stocks"]
        self.primary_stock: str = kw["primary_stock"]
        self.threshold: float = kw["threshold"]
        self.scan_interval: int = kw["scan_interval"]
        self.starting_capital: float = kw["starting_capital"]

        # Position management
        self.risk_per_trade: float = kw["risk_per_trade"]
        self.stop_loss_percent: float = kw["stop_loss_percent"]
        self.take_profit_percent: float = kw["take_profit_percent"]
        self.max_position_size: float = kw["max_position_size"]
        self.max_active_positions: int = kw["max_active_positions"]
        self.position_hold_time: int = kw["position_hold_time"]

        # Broker
        self.alpaca_api_key: str = kw["alpaca_api_key"]
        self.alpaca_secret_key: str = kw["alpaca_secret_key"]
        self.alpaca_base_url: str = kw["alpaca_base_url"]
        self.dry_run: bool = kw["dry_run"]

        # Safety
        self.max_daily_loss_percent: float = kw["max_daily_loss_percent"]

        # Notifications
        self.email_alerts: bool = kw.get("email_alerts", False)
        self.email_address: str = kw.get("email_address", "")
        self.email_password: str = kw.get("email_password", "")
        self.smtp_server: str = kw.get("smtp_server", "smtp.gmail.com")
        self.smtp_port: int = kw.get("smtp_port", 587)
        self.discord_webhook: str = kw.get("discord_webhook", "")
        self.discord_alerts: bool = kw.get("discord_alerts", False)
        self.telegram_token: str = kw.get("telegram_token", "")
        self.telegram_chat_id: str = kw.get("telegram_chat_id", "")
        self.telegram_alerts: bool = kw.get("telegram_alerts", False)

        # Dashboard
        self.dashboard_host: str = kw.get("dashboard_host", "127.0.0.1")
        self.dashboard_port: int = kw.get("dashboard_port", 8000)

        # Misc
        self.database_path: str = kw.get("database_path", "trading.db")
        self.log_level: str = kw.get("log_level", "INFO")
        self.max_workers: int = kw.get("max_workers", 4)
        self.news_api_key: str = kw.get("news_api_key", "")
        self.disable_finbert: bool = kw.get("disable_finbert", False)

        # Market hours
        self.market_open: float = kw.get("market_open", 9.5)
        self.market_close: float = kw.get("market_close", 16.0)
        self.trading_days: list[int] = kw.get("trading_days", [0, 1, 2, 3, 4])

        self._validate()

    # ------------------------------------------------------------------
    def _validate(self):
        if not self.stocks:
            raise ValueError("stocks list must not be empty")
        if self.primary_stock not in self.stocks:
            raise ValueError(
                f"primary_stock {self.primary_stock!r} must be in stocks list"
            )
        for pct_name in ("risk_per_trade", "stop_loss_percent", "take_profit_percent",
                         "max_position_size"):
            val = getattr(self, pct_name)
            if not (0 < val <= 1):
                raise ValueError(
                    f"{pct_name}={val} must be a fraction between 0 (exclusive) and 1"
                )
        if not (0 < self.threshold <= 1):
            raise ValueError(f"threshold={self.threshold} must be in (0, 1]")
        if self.scan_interval <= 0:
            raise ValueError(f"scan_interval={self.scan_interval} must be positive")
        if self.max_active_positions <= 0:
            raise ValueError(
                f"max_active_positions={self.max_active_positions} must be positive"
            )
        if not (0 < self.max_daily_loss_percent <= 1):
            raise ValueError(
                f"max_daily_loss_percent={self.max_daily_loss_percent} must be a positive "
                f"fraction (e.g. 0.05 means 5% loss limit)"
            )
        if self.market_close <= self.market_open:
            raise ValueError(
                f"market_close={self.market_close} must be later than market_open={self.market_open}"
            )
        for d in self.trading_days:
            if d not in range(7):
                raise ValueError(f"trading_days entry {d} must be in 0-6")

    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls) -> "TradingConfig":
        """Build a TradingConfig from environment variables and legacy config fallbacks."""
        stocks_raw = _env_str("STOCKS") or ",".join(_legacy("STOCKS", ["AAPL", "MSFT", "NVDA", "TSLA"]))
        stocks = [s.strip().upper() for s in stocks_raw.split(",") if s.strip()]

        primary = (_env_str("PRIMARY_STOCK") or _legacy("PRIMARY_STOCK", stocks[0])).upper()

        return cls(
            stocks=stocks,
            primary_stock=primary,
            threshold=_env_float("GOLD_MINE_THRESHOLD", _legacy("GOLD_MINE_THRESHOLD", 0.75)),
            scan_interval=_env_int("SCAN_INTERVAL", _legacy("SCAN_INTERVAL", 30)),
            starting_capital=_env_float("STARTING_CAPITAL", _legacy("STARTING_CAPITAL", 500.0)),
            risk_per_trade=_env_float("RISK_PER_TRADE", _legacy("RISK_PER_TRADE", 0.10)),
            stop_loss_percent=_env_float("STOP_LOSS_PERCENT", _legacy("STOP_LOSS_PERCENT", 0.05)),
            take_profit_percent=_env_float("TAKE_PROFIT_PERCENT", _legacy("TAKE_PROFIT_PERCENT", 0.15)),
            max_position_size=_env_float("MAX_POSITION_SIZE", _legacy("MAX_POSITION_SIZE", 0.20)),
            max_active_positions=_env_int("MAX_ACTIVE_POSITIONS", _legacy("MAX_ACTIVE_POSITIONS", 5)),
            position_hold_time=_env_int("POSITION_HOLD_TIME", _legacy("POSITION_HOLD_TIME", 86400)),
            alpaca_api_key=_env_str("ALPACA_API_KEY", _legacy("ALPACA_API_KEY", "")),
            alpaca_secret_key=_env_str("ALPACA_SECRET_KEY", _legacy("ALPACA_SECRET_KEY", "")),
            alpaca_base_url=_env_str(
                "ALPACA_BASE_URL",
                _legacy("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
            ),
            dry_run=_env_bool("DRY_RUN", True),  # default safe: dry-run on
            max_daily_loss_percent=abs(
                _env_float("MAX_DAILY_LOSS_PERCENT", abs(_legacy("MAX_DAILY_LOSS_PERCENT", 0.05)))
            ),
            email_alerts=_env_bool("EMAIL_ALERTS", _legacy("EMAIL_ALERTS", False)),
            email_address=_env_str("EMAIL_ADDRESS", _legacy("EMAIL_ADDRESS", "")),
            email_password=_env_str("EMAIL_PASSWORD", _legacy("EMAIL_PASSWORD", "")),
            smtp_server=_env_str("SMTP_SERVER", _legacy("SMTP_SERVER", "smtp.gmail.com")),
            smtp_port=_env_int("SMTP_PORT", _legacy("SMTP_PORT", 587)),
            discord_webhook=_env_str("DISCORD_WEBHOOK", _legacy("DISCORD_WEBHOOK", "")),
            discord_alerts=_env_bool("DISCORD_ALERTS", _legacy("DISCORD_ALERTS", False)),
            telegram_token=_env_str("TELEGRAM_TOKEN", _legacy("TELEGRAM_TOKEN", "")),
            telegram_chat_id=_env_str("TELEGRAM_CHAT_ID", _legacy("TELEGRAM_CHAT_ID", "")),
            telegram_alerts=_env_bool("TELEGRAM_ALERTS", _legacy("TELEGRAM_ALERTS", False)),
            dashboard_host=_env_str("DASHBOARD_HOST", "127.0.0.1"),
            dashboard_port=_env_int("DASHBOARD_PORT", 8000),
            database_path=_env_str("DATABASE_PATH", "trading.db"),
            log_level=_env_str("LOG_LEVEL", "INFO"),
            max_workers=_env_int("MAX_WORKERS", _legacy("MAX_WORKERS", 4)),
            news_api_key=_env_str("NEWS_API_KEY", _legacy("NEWS_API_KEY", "")),
            disable_finbert=_env_bool("DISABLE_FINBERT", False),
            market_open=_coerce_time(_env_str("MARKET_OPEN") or _legacy("MARKET_OPEN", 9.5)),
            market_close=_coerce_time(_env_str("MARKET_CLOSE") or _legacy("MARKET_CLOSE", 16.0)),
            trading_days=[
                int(d.strip())
                for d in (_env_str("TRADING_DAYS") or "0,1,2,3,4").split(",")
                if d.strip()
            ],
        )

    def __repr__(self) -> str:
        return (
            f"TradingConfig(stocks={self.stocks!r}, dry_run={self.dry_run}, "
            f"threshold={self.threshold}, dashboard_port={self.dashboard_port})"
        )
