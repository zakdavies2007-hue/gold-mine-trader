from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from threading import Thread
from zoneinfo import ZoneInfo

from alpaca_broker import AlpacaBroker, BrokerGuardrailError
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
    """
    Market-hours scanner and execution loop.

    Position management (stop-loss, take-profit, max-hold exits) runs on EVERY
    cycle regardless of market hours, because a locally-evaluated threshold check
    provides no guarantee when the market re-opens after overnight or weekend gaps.

    Entry scanning is restricted to market hours to avoid placing orders when
    the exchange is closed.

    Limitation: exit orders are market-sell orders submitted via the REST API.
    They are not broker-native stop orders, so they are only evaluated when this
    process is running. A true guaranteed stop-loss would require a broker-native
    stop/bracket order submitted at entry time.
    """

    def __init__(
        self,
        detector,
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

    def manage_positions(self) -> list:
        """
        Evaluate open positions and submit exit orders if needed.
        Runs regardless of market hours.
        """
        actions = []
        for position in self.store.get_open_positions():
            try:
                data = self.detector.get_price_data(position['symbol'])
            except Exception as exc:
                LOGGER.warning('Price data unavailable for %s: %s', position['symbol'], exc)
                continue
            if data is None or getattr(data, 'empty', True):
                continue
            current_price = float(data['Close'].iloc[-1])
            decision = self.positions.evaluate_exit(position, current_price)
            if decision.action != 'sell':
                continue
            try:
                order = self.broker.submit_order(
                    symbol=position['symbol'],
                    qty=int(float(position['quantity'])),
                    side='sell',
                    client_order_id=f"gmt-close-{position['id']}",
                )
            except BrokerGuardrailError as exc:
                LOGGER.warning('Exit order failed for position %s: %s', position['id'], exc)
                continue
            closed_trade = self.store.close_trade(position['id'], current_price)
            actions.append({'order': order, 'trade': closed_trade, 'reason': decision.reason})
            if closed_trade:
                try:
                    self.notifier.send_trade_alert(closed_trade)
                except Exception as exc:
                    LOGGER.warning('Notification failed: %s', exc)
        return actions

    def reconcile_pending_intents(self) -> None:
        """
        On startup or each cycle, check for order_intents that are still 'pending'
        (process may have crashed after broker submission but before local recording).
        Query the broker to discover what actually happened and update local state.
        """
        for intent in self.store.get_pending_order_intents():
            client_order_id = intent['client_order_id']
            broker_order = self.broker.get_order_by_client_id(client_order_id)
            if broker_order is not None:
                broker_order_id = broker_order.get('id')
                status = broker_order.get('status', 'unknown')
                self.store.update_order_intent(client_order_id, status='filled', broker_order_id=broker_order_id)
                LOGGER.info(
                    'Reconciled pending intent %s -> broker order %s (%s)',
                    client_order_id, broker_order_id, status,
                )
            else:
                LOGGER.info('Pending intent %s: broker order not found, leaving as pending.', client_order_id)

    def scan_cycle(self, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)

        # Always run position management regardless of market hours.
        # NOTE: exit orders are market-sells; they are NOT broker-native stops.
        # They are only effective while this process is running.
        managed_positions = self.manage_positions()

        if not self.clock.is_market_open(now):
            return {'status': 'market_closed', 'managed_positions': managed_positions}

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
            if not self.positions.can_open_position(
                account_equity=equity,
                daily_pnl=summary['daily_pnl'],
                open_positions=len(open_positions),
            ):
                continue
            quantity = self.positions.calculate_quantity(price=float(result['price']), account_equity=equity)
            if quantity <= 0:
                continue
            if execution_blocked_reason:
                continue

            exits = self.positions.build_exit_levels(float(result['price']))
            client_order_id = f"gmt-{symbol}-{int(now.timestamp())}"

            # Persist the intent BEFORE submitting to broker.
            # If the process crashes after submission but before open_trade(), the
            # next cycle's reconcile_pending_intents() can recover the broker order.
            already_exists = not self.store.persist_order_intent(
                client_order_id=client_order_id,
                symbol=symbol,
                side='buy',
                quantity=quantity,
            )
            if already_exists:
                LOGGER.info('Skipping duplicate order intent for %s (%s)', symbol, client_order_id)
                continue

            try:
                order = self.broker.submit_order(
                    symbol=symbol,
                    qty=quantity,
                    side='buy',
                    client_order_id=client_order_id,
                )
            except BrokerGuardrailError as exc:
                LOGGER.warning('Order skipped for %s: %s', symbol, exc)
                self.store.update_order_intent(client_order_id, status='error', error=str(exc))
                continue

            broker_order_id = order.get('id')
            self.store.update_order_intent(client_order_id, status='submitted', broker_order_id=broker_order_id)
            self.store.register_signal(symbol, signal_key, created_at=now.isoformat())

            try:
                trade_id = self.store.open_trade(
                    symbol=symbol,
                    quantity=quantity,
                    entry_price=float(result['price']),
                    stop_loss=exits['stop_loss'],
                    take_profit=exits['take_profit'],
                    client_order_id=client_order_id,
                    broker_order_id=broker_order_id,
                    gold_mine_score=float(result['gold_mine_score']),
                    metadata={'research': result.get('research', {}), 'order': order},
                )
                self.store.update_order_intent(client_order_id, status='recorded')
            except Exception as exc:
                # Broker order submitted but local record failed.
                # The pending intent remains with status='submitted'.
                # reconcile_pending_intents() will handle this on the next cycle.
                LOGGER.error(
                    'Local trade record failed for %s (order %s): %s. '
                    'Order intent preserved for reconciliation.',
                    symbol, broker_order_id, exc,
                )
                continue

            trade = {
                'id': trade_id,
                'symbol': symbol,
                'side': 'buy',
                'quantity': quantity,
                'entry_price': float(result['price']),
            }
            try:
                self.notifier.send_trade_alert(trade)
            except Exception as exc:
                LOGGER.warning('Notification failed: %s', exc)
            executed.append(trade)
            open_positions.append({'symbol': symbol})

        return {
            'status': 'ok',
            'executed': executed,
            'managed_positions': managed_positions,
            'account': account,
        }


def build_app(config: TradingConfig | None = None):
    from gold_mine_trader import GoldMineTrader
    config = config or TradingConfig.from_env()
    clock = MarketClock(
        config.market_timezone,
        config.market_open,
        config.market_close,
        config.trading_days,
    )
    store = TradeStore(config.database_path)
    broker = AlpacaBroker(config)
    positions = PositionManager(config)
    from notifications import NotificationManager
    notifier = NotificationManager(config)
    from dashboard import DashboardServer
    dashboard = DashboardServer(store, host=config.dashboard_host, port=config.dashboard_port)
    detector = GoldMineTrader(symbol=config.primary_stock)
    trader = AutoTrader(
        detector=detector,
        broker=broker,
        store=store,
        positions=positions,
        notifier=notifier,
        config=config,
        clock=clock,
    )
    return trader, dashboard


def run(config: TradingConfig | None = None):
    import logging
    logging.basicConfig(level=logging.INFO)
    config = config or TradingConfig.from_env()
    trader, dashboard = build_app(config)
    dashboard_thread = dashboard.start_background()

    try:
        trader.reconcile_pending_intents()
        while True:
            try:
                result = trader.scan_cycle()
                LOGGER.info('Cycle result: %s', result.get('status'))
            except Exception as exc:
                LOGGER.error('Scan cycle error: %s', exc)
            time.sleep(config.scan_interval)
    finally:
        dashboard.stop()


if __name__ == '__main__':
    run()
