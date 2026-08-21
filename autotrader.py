"""
autotrader.py – Main trading loop with order-intent reconciliation.

Order-intent reconciliation
---------------------------
After the process submits an order and before the local trade record is
written, a crash leaves the database in an ambiguous state.  On startup (and
each reconciliation pass) the autotrader:

1. Queries pending/submitted local intents.
2. For each, queries the broker by URL-encoded client_order_id.
3. Maps the broker status to the local intent:

   broker status        → local action
   ─────────────────    ─────────────────────────────────────────────
   filled               → mark intent=filled, status=open (do NOT mark closed)
   accepted / new /
   pending_new          → leave as submitted (recoverable)
   canceled / expired /
   rejected             → mark terminal; do NOT open a position
   (no broker order)    → if intent=pending, leave; if =submitted, mark terminal

4. If a broker order is filled but no local record exists, reconstruct a
   minimal local trade marked as 'reconciled_from_broker' so the position
   is tracked.

Market hours
------------
Position management (stop-loss / take-profit exits) runs outside market hours
because exits are local REST calls, not broker-native stops.  This means exits
may NOT fire if the process is down.

This module is intentionally single-file for clarity.
"""

from __future__ import annotations

import logging
import os
import signal
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

log = logging.getLogger(__name__)

# Terminal broker statuses – do not open a local position for these
_TERMINAL_STATUSES = frozenset(
    {"canceled", "cancelled", "expired", "rejected", "replaced"}
)
# Statuses that confirm the order is live (awaiting fill or partially filled)
_RECOVERABLE_STATUSES = frozenset(
    {"accepted", "new", "pending_new", "partially_filled", "pending_cancel",
     "pending_replace", "held"}
)


class MarketClock:
    """Determine whether the market is currently open."""

    def __init__(
        self,
        market_open: float = 9.5,
        market_close: float = 16.0,
        trading_days: list[int] | None = None,
    ) -> None:
        self.market_open = market_open
        self.market_close = market_close
        self.trading_days = trading_days or [0, 1, 2, 3, 4]

    def is_market_open(self, now: datetime | None = None) -> bool:
        """Return True when the market is currently open (ignores holidays)."""
        if now is None:
            now = datetime.now(timezone.utc)
        # Convert UTC to US/Eastern (simple offset; does not handle DST perfectly)
        et = now - timedelta(hours=4)  # EDT approximation
        if et.weekday() not in self.trading_days:
            return False
        hour_frac = et.hour + et.minute / 60.0
        return self.market_open <= hour_frac < self.market_close


class AutoTrader:
    """Main trading orchestrator."""

    def __init__(
        self,
        config: Any,
        detector: Any,
        broker: Any,
        trade_store: Any,
        position_manager: Any,
        notifier: Any | None = None,
        clock: MarketClock | None = None,
    ) -> None:
        self.config = config
        self.detector = detector
        self.broker = broker
        self.store = trade_store
        self.pm = position_manager
        self.notifier = notifier
        self.clock = clock or MarketClock(
            config.market_open, config.market_close, config.trading_days
        )
        self._stop_flag = False

    # ------------------------------------------------------------------
    # Signal handling for graceful shutdown
    # ------------------------------------------------------------------

    def _handle_signal(self, *_):
        log.info("Shutdown signal received; stopping after current cycle")
        self._stop_flag = True

    # ------------------------------------------------------------------
    # Order-intent reconciliation
    # ------------------------------------------------------------------

    def reconcile_pending_intents(self) -> int:
        """Reconcile all pending/submitted intents against broker state.

        Returns the number of intents processed.
        """
        intents = self.store.get_pending_intents()
        if not intents:
            return 0

        log.info("Reconciling %d pending intent(s)…", len(intents))
        processed = 0

        for intent in intents:
            client_id = intent["client_order_id"]
            intent_status = intent.get("intent_status", "pending")
            log.debug("Reconciling intent %s (status=%s)", client_id, intent_status)

            try:
                broker_order = self.broker.get_order_by_client_id(client_id)
            except Exception as exc:
                log.warning("Broker query failed for %s: %s", client_id, exc)
                continue

            if broker_order is None:
                # No broker record
                if intent_status == "submitted":
                    # We submitted but broker has no record → likely a network failure;
                    # mark terminal to prevent phantom position
                    log.warning(
                        "Intent %s has status=submitted but no broker order found; "
                        "marking terminal",
                        client_id,
                    )
                    self.store.mark_terminal(client_id, "broker_order_not_found")
                # If still 'pending', leave it for the next cycle
                processed += 1
                continue

            broker_status = str(broker_order.get("status", "")).lower()
            broker_id = broker_order.get("id", "")

            if broker_status == "filled":
                # Update to open position with actual fill info
                fill_price = float(broker_order.get("filled_avg_price") or
                                   intent.get("entry_price") or 0)
                fill_qty = int(float(broker_order.get("filled_qty") or
                                     intent.get("entry_qty") or 0))
                log.info(
                    "Intent %s filled @ %.4f × %d; marking open",
                    client_id, fill_price, fill_qty,
                )
                self.store.set_intent_status(
                    client_id,
                    intent_status="filled",
                    broker_order_id=broker_id,
                    broker_order_data=broker_order,
                )
                # Update entry fields if fill data is available
                if fill_price > 0 and fill_qty > 0:
                    with self.store._connect() as conn:
                        conn.execute(
                            "UPDATE trades SET status='open', entry_price=?, entry_qty=? "
                            "WHERE client_order_id=?",
                            (fill_price, fill_qty, client_id),
                        )

            elif broker_status in _TERMINAL_STATUSES:
                log.info(
                    "Intent %s is terminal (broker_status=%s); marking terminal",
                    client_id, broker_status,
                )
                self.store.mark_terminal(client_id, reason="broker_terminal",
                                         broker_status=broker_status)

            elif broker_status in _RECOVERABLE_STATUSES:
                # Update broker_order_id but leave as submitted
                log.debug("Intent %s recoverable (broker_status=%s)", client_id, broker_status)
                self.store.set_intent_status(
                    client_id,
                    intent_status="submitted",
                    broker_order_id=broker_id,
                    broker_order_data=broker_order,
                )

            else:
                log.warning(
                    "Unknown broker status %r for intent %s; leaving as-is",
                    broker_status, client_id,
                )

            processed += 1

        return processed

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def manage_positions(self) -> list[dict]:
        """Check all open positions for exit conditions.

        Runs regardless of market hours (exits are local REST calls).
        """
        exits = []
        open_positions = self.store.get_open_positions()

        for pos in open_positions:
            symbol = pos["symbol"]
            client_id = pos["client_order_id"]
            entry_price = float(pos.get("entry_price") or 0)
            entry_qty = int(pos.get("entry_qty") or 0)
            entry_side = pos.get("entry_side", "buy")
            opened_at = pos.get("opened_at", "")

            if entry_price <= 0 or entry_qty <= 0:
                log.warning("Position %s has invalid entry data; skipping", client_id)
                continue

            # Get latest price
            try:
                from gold_mine_trader import get_price_data
                df = get_price_data(symbol, period="5d")
                if df is None or df.empty:
                    log.warning("No price data for %s; cannot evaluate exit", symbol)
                    continue
                closes = df["close"].dropna()
                if closes.empty:
                    continue
                current_price = float(closes.iloc[-1])
            except Exception as exc:
                log.error("Price fetch error for %s: %s", symbol, exc)
                continue

            import math
            if not math.isfinite(current_price) or current_price <= 0:
                log.warning("Non-finite price for %s; skipping exit check", symbol)
                continue

            decision = self.pm.evaluate_exit(
                entry_price=entry_price,
                current_price=current_price,
                opened_at=opened_at,
                side=entry_side,
            )

            if decision.should_exit:
                log.info(
                    "Exit signal for %s: reason=%s price=%.4f",
                    symbol, decision.reason, decision.exit_price,
                )
                exit_result = self._execute_exit(
                    symbol=symbol,
                    qty=entry_qty,
                    client_order_id=client_id,
                    exit_price=decision.exit_price,
                    exit_reason=decision.reason,
                )
                exits.append(exit_result)

        return exits

    def _execute_exit(
        self,
        symbol: str,
        qty: int,
        client_order_id: str,
        exit_price: float,
        exit_reason: str,
    ) -> dict:
        """Submit a sell order and record the exit."""
        exit_order_data: dict | None = None
        try:
            exit_coid = f"exit-{client_order_id[:32]}-{int(time.time())}"
            broker_resp = self.broker.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                client_order_id=exit_coid,
            )
            exit_order_data = broker_resp
            log.info("Exit order submitted: %s", broker_resp.get("id"))
        except Exception as exc:
            log.error("Exit order failed for %s: %s", symbol, exc)

        pnl = self.store.close_trade(
            client_order_id=client_order_id,
            exit_price=exit_price,
            exit_qty=qty,
            exit_reason=exit_reason,
            exit_side="sell",
            exit_order_data=exit_order_data,
        )

        if self.notifier:
            try:
                self.notifier.send(
                    f"EXIT {symbol} ({exit_reason})",
                    f"Symbol: {symbol}\nReason: {exit_reason}\n"
                    f"Exit price: {exit_price:.4f}\nP&L: {pnl:.2f}",
                )
            except Exception as exc:
                log.warning("Notification failed for exit %s: %s", symbol, exc)

        return {"symbol": symbol, "reason": exit_reason, "pnl": pnl}

    # ------------------------------------------------------------------
    # Scan cycle
    # ------------------------------------------------------------------

    def scan_cycle(self) -> dict:
        """Execute one full scan cycle.

        Returns a dict with keys: executions, exits, skipped, errors.
        """
        result: dict = {"executions": [], "exits": [], "skipped": [], "errors": []}
        is_open = self.clock.is_market_open()

        # Always manage positions (time / stop / take-profit exits run 24/7)
        try:
            exits = self.manage_positions()
            result["exits"].extend(exits)
        except Exception as exc:
            log.error("manage_positions error: %s", exc)
            result["errors"].append({"stage": "manage_positions", "error": str(exc)})

        # Reconcile pending intents
        try:
            self.reconcile_pending_intents()
        except Exception as exc:
            log.error("reconcile error: %s", exc)
            result["errors"].append({"stage": "reconcile", "error": str(exc)})

        if not is_open:
            log.debug("Market closed; skipping scan/execution")
            return result

        # Get account state once
        try:
            account = self.broker.get_account()
            equity = float(account.get("equity") or self.config.starting_capital)
            if not __import__("math").isfinite(equity) or equity <= 0:
                equity = self.config.starting_capital
        except Exception as exc:
            log.error("get_account error: %s", exc)
            equity = self.config.starting_capital

        open_positions = self.store.get_open_positions()
        summary = self.store.performance_summary()
        daily_pnl = summary.get("total_pnl", 0.0)

        # Scan symbols
        try:
            scan_results = self.detector.scan_multiple_stocks(self.config.stocks)
        except Exception as exc:
            log.error("Scan error: %s", exc)
            result["errors"].append({"stage": "scan", "error": str(exc)})
            return result

        for res in scan_results:
            symbol = res.symbol

            if not res.eligible:
                result["skipped"].append(
                    {"symbol": symbol, "reason": f"degraded:{res.degraded_providers}"}
                )
                continue

            if not res.is_gold_mine:
                continue

            # Safety: never execute a zero or non-finite price
            import math
            if not math.isfinite(res.latest_price) or res.latest_price <= 0:
                result["skipped"].append(
                    {"symbol": symbol, "reason": "invalid_price"}
                )
                continue

            can_open, reason = self.pm.can_open_position(
                len(open_positions), daily_pnl
            )
            if not can_open:
                result["skipped"].append({"symbol": symbol, "reason": reason})
                continue

            # Dedup signal
            signal_key = f"gold_mine_{res.score:.4f}"
            if self.store.has_recent_signal(symbol, signal_key, hours=24):
                result["skipped"].append(
                    {"symbol": symbol, "reason": "duplicate_signal"}
                )
                continue

            # Calculate position size
            qty = self.pm.position_size(equity, res.latest_price, self.config.risk_per_trade)
            if qty <= 0:
                result["skipped"].append({"symbol": symbol, "reason": "insufficient_capital"})
                continue

            # Generate unique client_order_id
            client_order_id = (
                f"gmt-{symbol.lower()}-"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-"
                f"{uuid.uuid4().hex[:8]}"
            )[:48]

            # Write intent BEFORE submitting to broker (pending)
            trade_id = self.store.open_trade(
                symbol=symbol,
                client_order_id=client_order_id,
                entry_side="buy",
                entry_price=res.latest_price,
                entry_qty=qty,
                stop_loss=res.latest_price * (1 - self.config.stop_loss_percent),
                take_profit=res.latest_price * (1 + self.config.take_profit_percent),
                metadata={"score": res.score, "signal_key": signal_key},
            )

            # Update intent to submitted before broker call
            # (crash here: intent_status=pending → reconcile leaves as pending)
            self.store.set_intent_status(client_order_id, "submitted")

            try:
                broker_resp = self.broker.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    client_order_id=client_order_id,
                )
                broker_id = broker_resp.get("id", "")
                broker_status = broker_resp.get("status", "accepted")

                # Update with broker response
                self.store.set_intent_status(
                    client_order_id,
                    intent_status=broker_status,
                    broker_order_id=broker_id,
                    broker_order_data=broker_resp,
                )

                # Register signal cooldown
                self.store.register_signal(symbol, signal_key, res.score)

                open_positions.append({"symbol": symbol})  # local counter

                if self.notifier:
                    try:
                        self.notifier.send(
                            f"BUY {symbol}",
                            f"Symbol: {symbol}\nScore: {res.score:.4f}\n"
                            f"Price: {res.latest_price:.4f}\nQty: {qty}",
                        )
                    except Exception as exc:
                        log.warning("Notification failed for %s buy: %s", symbol, exc)

                result["executions"].append(
                    {
                        "symbol": symbol,
                        "qty": qty,
                        "price": res.latest_price,
                        "score": res.score,
                        "broker_status": broker_status,
                    }
                )
                log.info("Executed BUY %d %s @ %.4f (score=%.4f)", qty, symbol, res.latest_price, res.score)

            except Exception as exc:
                log.error("Order submission failed for %s: %s", symbol, exc)
                result["errors"].append({"symbol": symbol, "error": str(exc)})
                # Leave intent as 'submitted'; reconciliation will resolve it

        return result

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the trading loop until stopped."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        log.info("AutoTrader started (dry_run=%s)", self.config.dry_run)

        # Reconcile any intents left over from a previous run
        try:
            self.reconcile_pending_intents()
        except Exception as exc:
            log.error("Startup reconciliation error: %s", exc)

        while not self._stop_flag:
            try:
                cycle_result = self.scan_cycle()
                log.info(
                    "Cycle complete: %d executions, %d exits, %d skipped, %d errors",
                    len(cycle_result["executions"]),
                    len(cycle_result["exits"]),
                    len(cycle_result["skipped"]),
                    len(cycle_result["errors"]),
                )
            except Exception as exc:
                log.error("Unexpected scan_cycle error: %s", exc)

            if not self._stop_flag:
                time.sleep(self.config.scan_interval)

        log.info("AutoTrader stopped cleanly")
