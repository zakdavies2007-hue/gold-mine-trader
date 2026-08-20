from __future__ import annotations

import logging
import time
from threading import Thread
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from alpaca_broker import AlpacaBroker, BrokerGuardrailError
from dashboard import DashboardServer
from notifications import NotificationManager
from position_manager import PositionManager
from trade_store import TradeStore
from trading_config import TradingConfig

LOGGER = logging.getLogger(__name__)


class MarketClock:
    def __init__(self, timezone_name: str, market_open: str, market_close: str, trading_days):
        self.zone = ZoneInfo(timezone_name)
        self.market_open = self._parse_time(market_open)
        self.market_close = self._parse_time(market_close)
        self.trading_days = set(trading_days)

    @staticmethod
    def _parse_time(value: str):
        hours, minutes = value.split(':', 1)
        return int(hours), int(minutes)

    def is_market_open(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        local_now = now.astimezone(self.zone)
        if local_now.weekday() not in self.trading_days:
            return False
        open_hour, open_minute = self.market_open
        close_hour, close_minute = self.market_close
        open_tuple = (open_hour, open_minute)
        close_tuple = (close_hour, close_minute)
        current = (local_now.hour, local_now.minute)
        return open_tuple <= current < close_tuple


class AutoTrader:
    def __init__(
        self,
        detector: GoldMineTrader,
        broker: AlpacaBroker,
        store: TradeStore,
        positions: PositionManager,
        notifier: NotificationManager,
        config: TradingConfig,
        clock: MarketClock,
    ):
        self.detector = detector
        self.broker = broker
        self.store = store
        self.positions = positions
        self.notifier = notifier
        self.config = config
        self.clock = clock

    def _signal_key(self, result):
        return f"{result['symbol']}:{result['gold_mine_score']:.4f}:{result['price']:.2f}"

    def manage_positions(self):
        actions = []
        for position in self.store.get_open_positions():
            data = self.detector.get_price_data(position['symbol'])
            if data is None or data.empty:
                continue
            current_price = float(data['Close'].iloc[-1])
            decision = self.positions.evaluate_exit(position, current_price)
            if decision.action != 'sell':
                continue
            order = self.broker.submit_order(
                symbol=position['symbol'],
                qty=int(float(position['quantity'])),
                side='sell',
                client_order_id=f"gmt-close-{position['id']}",
            )
            closed_trade = self.store.close_trade(position['id'], current_price)
            actions.append({'order': order, 'trade': closed_trade, 'reason': decision.reason})
            if closed_trade:
                self.notifier.send_trade_alert(closed_trade)
        return actions

    def scan_cycle(self, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if not self.clock.is_market_open(now):
            return {'status': 'market_closed'}

        execution_blocked_reason = None
        try:
            account = self.broker.get_account()
            equity = float(account.get('equity') or self.config.starting_capital)
        except BrokerGuardrailError as exc:
            execution_blocked_reason = str(exc)
            LOGGER.warning('Execution disabled for this cycle: %s', exc)
            account = {'status': 'blocked'}
            equity = self.config.starting_capital
        summary = self.store.performance_summary(now)
        open_positions = self.store.get_open_positions()

        executed = []
        for symbol, result in self.detector.scan_multiple_stocks(self.config.stocks).items():
            self.store.record_scan(result)
            if not result['is_gold_mine']:
                continue
            signal_key = self._signal_key(result)
            if self.store.has_recent_signal(symbol, signal_key, self.config.scan_interval * 2):
                continue
            if any(position['symbol'] == symbol for position in open_positions):
                continue
            if not self.positions.can_open_position(account_equity=equity, daily_pnl=summary['daily_pnl'], open_positions=len(open_positions)):
                continue
            quantity = self.positions.calculate_quantity(price=float(result['price']), account_equity=equity)
            if quantity <= 0:
                continue
            if execution_blocked_reason:
                continue
            exits = self.positions.build_exit_levels(float(result['price']))
            client_order_id = f"gmt-{symbol}-{int(now.timestamp())}"
            try:
                order = self.broker.submit_order(symbol=symbol, qty=quantity, side='buy', client_order_id=client_order_id)
            except BrokerGuardrailError as exc:
                LOGGER.warning('Order skipped for %s: %s', symbol, exc)
                continue
            self.store.register_signal(symbol, signal_key, created_at=now.isoformat())
            trade_id = self.store.open_trade(
                symbol=symbol,
                quantity=quantity,
                entry_price=float(result['price']),
                stop_loss=exits['stop_loss'],
                take_profit=exits['take_profit'],
                client_order_id=client_order_id,
                gold_mine_score=float(result['gold_mine_score']),
                metadata={'research': result.get('research', {}), 'order': order},
            )
            trade = {'id': trade_id, 'symbol': symbol, 'side': 'buy', 'quantity': quantity, 'entry_price': float(result['price'])}
            self.notifier.send_trade_alert(trade)
            executed.append(trade)
            open_positions.append({'symbol': symbol})
        managed_positions = [] if execution_blocked_reason else self.manage_positions()
        return {'status': 'ok', 'executed': executed, 'managed_positions': managed_positions, 'account': account}


def build_app(config: TradingConfig | None = None):
    from gold_mine_trader import GoldMineTrader

    config = config or TradingConfig.from_env()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    detector = GoldMineTrader(symbol=config.primary_stock)
    broker = AlpacaBroker(config)
    store = TradeStore(config.database_path)
    positions = PositionManager(config)
    notifier = NotificationManager(config)
    clock = MarketClock(config.market_timezone, config.market_open, config.market_close, config.trading_days)
    return AutoTrader(detector, broker, store, positions, notifier, config, clock), DashboardServer(store, config.dashboard_host, config.dashboard_port)


def main():
    trader, dashboard = build_app()
    LOGGER.info('Dashboard available on http://%s:%s', dashboard.host, dashboard.port)
    LOGGER.info('Starting trading loop in %s mode (dry_run=%s)', trader.config.trading_mode, trader.config.dry_run)
    Thread(target=dashboard.serve_forever, daemon=True).start()
    while True:
        try:
            result = trader.scan_cycle()
            if result['status'] == 'market_closed':
                LOGGER.info('Market closed, waiting...')
            else:
                LOGGER.info('Scan cycle completed: %s', result)
        except Exception as exc:  # pragma: no cover - integration protection
            LOGGER.exception('Trading loop failed: %s', exc)
        time.sleep(trader.config.scan_interval)


if __name__ == '__main__':
    main()
