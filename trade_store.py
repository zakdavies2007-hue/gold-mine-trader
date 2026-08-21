"""
trade_store.py – SQLite-backed persistence for trades, signals, and metrics.

Design choices
--------------
* WAL journal mode and a 5-second busy timeout to tolerate concurrent readers.
* Parent directories are created automatically.
* A unique constraint on client_order_id prevents duplicate records.
* Entry and exit data are stored in separate columns; the entry side is never
  overwritten.
* Timezone-aware UTC timestamps (ISO 8601 with 'Z' suffix).
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


class TradeStore:
    """Manages all SQLite persistence for the trading system."""

    def __init__(self, db_path: str = "trading.db") -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    client_order_id TEXT UNIQUE NOT NULL,
                    broker_order_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    intent_status TEXT NOT NULL DEFAULT 'pending',
                    entry_side TEXT NOT NULL DEFAULT 'buy',
                    entry_price REAL,
                    entry_qty INTEGER,
                    entry_order_data TEXT,
                    exit_side TEXT,
                    exit_price REAL,
                    exit_qty INTEGER,
                    exit_order_data TEXT,
                    exit_reason TEXT,
                    pnl REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    metadata TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_opened_at ON trades(opened_at);

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    signal_key TEXT NOT NULL,
                    score REAL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
                CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at);

                CREATE TABLE IF NOT EXISTS performance_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    total_trades INTEGER,
                    winning_trades INTEGER,
                    total_pnl REAL,
                    win_rate REAL,
                    metadata TEXT
                );
                """
            )
            # Insert schema version if not present
            conn.execute(
                "INSERT OR IGNORE INTO schema_version VALUES (?)", (_SCHEMA_VERSION,)
            )

    # ------------------------------------------------------------------
    # Trade lifecycle
    # ------------------------------------------------------------------

    def open_trade(
        self,
        symbol: str,
        client_order_id: str,
        entry_side: str,
        entry_price: float,
        entry_qty: int,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        broker_order_id: str | None = None,
        entry_order_data: dict | None = None,
        metadata: dict | None = None,
        opened_at: str | None = None,
    ) -> int:
        """Insert a new trade record; return the row id."""
        ts = opened_at or _now_utc()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO trades (
                    symbol, client_order_id, broker_order_id, status, intent_status,
                    entry_side, entry_price, entry_qty, entry_order_data,
                    stop_loss, take_profit, opened_at, metadata
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    symbol.upper(),
                    client_order_id,
                    broker_order_id,
                    "open",
                    "submitted",
                    entry_side,
                    entry_price,
                    entry_qty,
                    json.dumps(entry_order_data) if entry_order_data else None,
                    stop_loss,
                    take_profit,
                    ts,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            return cur.lastrowid

    def set_intent_status(
        self,
        client_order_id: str,
        intent_status: str,
        broker_order_id: str | None = None,
        broker_order_data: dict | None = None,
    ) -> None:
        """Update the intent_status (and optionally broker_order_id) for a pending trade."""
        with self._connect() as conn:
            if broker_order_id:
                conn.execute(
                    """
                    UPDATE trades SET intent_status=?, broker_order_id=?, entry_order_data=?
                    WHERE client_order_id=?
                    """,
                    (
                        intent_status,
                        broker_order_id,
                        json.dumps(broker_order_data) if broker_order_data else None,
                        client_order_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE trades SET intent_status=? WHERE client_order_id=?",
                    (intent_status, client_order_id),
                )

    def close_trade(
        self,
        client_order_id: str,
        exit_price: float,
        exit_qty: int,
        exit_reason: str = "manual",
        exit_side: str = "sell",
        exit_order_data: dict | None = None,
        closed_at: str | None = None,
    ) -> float:
        """Close a trade by client_order_id; return P&L."""
        ts = closed_at or _now_utc()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT entry_price, entry_qty, entry_side FROM trades WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"No trade found for client_order_id={client_order_id!r}")

            entry_price = row["entry_price"] or 0.0
            entry_qty = row["entry_qty"] or 0
            entry_side = row["entry_side"] or "buy"

            # P&L: for long (buy) entries, profit when exit > entry
            if entry_side == "buy":
                pnl = (exit_price - entry_price) * min(exit_qty, entry_qty)
            else:
                pnl = (entry_price - exit_price) * min(exit_qty, entry_qty)

            if not math.isfinite(pnl):
                pnl = 0.0

            conn.execute(
                """
                UPDATE trades SET
                    status='closed',
                    exit_side=?, exit_price=?, exit_qty=?,
                    exit_order_data=?, exit_reason=?,
                    pnl=?, closed_at=?
                WHERE client_order_id=?
                """,
                (
                    exit_side,
                    exit_price,
                    exit_qty,
                    json.dumps(exit_order_data) if exit_order_data else None,
                    exit_reason,
                    pnl,
                    ts,
                    client_order_id,
                ),
            )
        return pnl

    def mark_terminal(
        self,
        client_order_id: str,
        reason: str,
        broker_status: str | None = None,
    ) -> None:
        """Mark a trade as terminal (cancelled/rejected) without opening a position."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE trades SET
                    status='terminal', intent_status=?,
                    exit_reason=?, closed_at=?
                WHERE client_order_id=?
                """,
                (broker_status or reason, reason, _now_utc(), client_order_id),
            )

    def get_trade(self, client_order_id: str) -> dict | None:
        """Return a single trade by client_order_id or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trades WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_open_positions(self) -> list[dict]:
        """Return all open trade records."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status='open' ORDER BY opened_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_pending_intents(self) -> list[dict]:
        """Return trades whose intent_status is 'pending' or 'submitted' (recoverable)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM trades
                   WHERE intent_status IN ('pending', 'submitted')
                   AND status NOT IN ('closed', 'terminal')
                   ORDER BY opened_at ASC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_trades(self, limit: int = 50) -> list[dict]:
        """Return the most recent closed trades."""
        limit = max(1, min(limit, 1000))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def register_signal(self, symbol: str, signal_key: str, score: float = 0.0) -> bool:
        """Record a signal; return True if inserted (False if key already seen recently)."""
        # Cooldown: reject if same symbol+key seen within the last 24 hours
        cooldown_cutoff = datetime.now(timezone.utc)
        cutoff_str = (
            datetime(
                cooldown_cutoff.year, cooldown_cutoff.month, cooldown_cutoff.day,
                cooldown_cutoff.hour, cooldown_cutoff.minute, cooldown_cutoff.second,
                tzinfo=timezone.utc,
            ).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        )
        # Calculate 24 hours ago
        from datetime import timedelta
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        ) + "Z"

        with self._connect() as conn:
            existing = conn.execute(
                """SELECT id FROM signals
                   WHERE symbol=? AND signal_key=? AND created_at >= ?""",
                (symbol.upper(), signal_key, cutoff_24h),
            ).fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO signals (symbol, signal_key, score, created_at) VALUES (?,?,?,?)",
                (symbol.upper(), signal_key, score, _now_utc()),
            )
        return True

    def has_recent_signal(self, symbol: str, signal_key: str, hours: int = 24) -> bool:
        """Return True if a signal for this symbol+key was recorded within *hours*."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        ) + "Z"
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id FROM signals
                   WHERE symbol=? AND signal_key=? AND created_at >= ?""",
                (symbol.upper(), signal_key, cutoff),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Performance summary
    # ------------------------------------------------------------------

    def performance_summary(self) -> dict[str, Any]:
        """Return aggregate performance metrics."""
        with self._connect() as conn:
            closed = conn.execute(
                "SELECT pnl FROM trades WHERE status='closed'"
            ).fetchall()
            open_pos = conn.execute(
                "SELECT id FROM trades WHERE status='open'"
            ).fetchall()

        pnls = [row["pnl"] for row in closed if row["pnl"] is not None]
        total = len(pnls)
        winners = sum(1 for p in pnls if p > 0)
        total_pnl = sum(pnls)
        win_rate = winners / total if total else 0.0

        return {
            "total_trades": total,
            "winning_trades": winners,
            "losing_trades": total - winners,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "open_positions": len(open_pos),
        }
