from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional


class TradeStore:
    def __init__(self, database_path: str):
        self.database_path = Path(database_path)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self):
        with self.connect() as connection:
            connection.executescript(
                '''
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    signal_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, signal_key)
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    status TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    exit_price REAL,
                    pnl REAL,
                    gold_mine_score REAL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                '''
            )

    def record_scan(self, result: Dict):
        with self.connect() as connection:
            connection.execute(
                'INSERT INTO scans(symbol, created_at, payload) VALUES (?, ?, ?)',
                (result['symbol'], result['timestamp'], json.dumps(result)),
            )

    def register_signal(self, symbol: str, signal_key: str, created_at: Optional[str] = None) -> bool:
        created_at = created_at or datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            try:
                connection.execute(
                    'INSERT INTO signals(symbol, signal_key, created_at) VALUES (?, ?, ?)',
                    (symbol, signal_key, created_at),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def has_recent_signal(self, symbol: str, signal_key: str, cooldown_seconds: int) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)).isoformat()
        with self.connect() as connection:
            row = connection.execute(
                'SELECT 1 FROM signals WHERE symbol = ? AND signal_key = ? AND created_at >= ? LIMIT 1',
                (symbol, signal_key, cutoff),
            ).fetchone()
            return row is not None

    def open_trade(
        self,
        *,
        symbol: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        client_order_id: str,
        gold_mine_score: float,
        metadata: Optional[Dict] = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                '''
                INSERT INTO trades(symbol, side, quantity, entry_price, stop_loss, take_profit, status, client_order_id, opened_at, gold_mine_score, metadata)
                VALUES (?, 'buy', ?, ?, ?, ?, 'open', ?, ?, ?, ?)
                ''',
                (
                    symbol,
                    quantity,
                    entry_price,
                    stop_loss,
                    take_profit,
                    client_order_id,
                    datetime.now(timezone.utc).isoformat(),
                    gold_mine_score,
                    json.dumps(metadata or {}),
                ),
            )
            return int(cursor.lastrowid)

    def close_trade(self, trade_id: int, exit_price: float, closed_at: Optional[str] = None) -> Optional[Dict]:
        closed_at = closed_at or datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM trades WHERE id = ? AND status = ?', (trade_id, 'open')).fetchone()
            if row is None:
                return None
            pnl = (float(exit_price) - float(row['entry_price'])) * float(row['quantity'])
            connection.execute(
                'UPDATE trades SET status = ?, side = ?, closed_at = ?, exit_price = ?, pnl = ? WHERE id = ?',
                ('closed', 'sell', closed_at, float(exit_price), pnl, trade_id),
            )
            payload = dict(row)
            payload.update({'status': 'closed', 'side': 'sell', 'closed_at': closed_at, 'exit_price': float(exit_price), 'pnl': pnl})
            return payload

    def get_open_positions(self) -> List[Dict]:
        with self.connect() as connection:
            rows = connection.execute('SELECT * FROM trades WHERE status = ? ORDER BY opened_at ASC', ('open',)).fetchall()
            return [dict(row) for row in rows]

    def get_recent_trades(self, limit: int = 20) -> List[Dict]:
        with self.connect() as connection:
            rows = connection.execute('SELECT * FROM trades ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
            return [dict(row) for row in rows]

    def performance_summary(self, now: Optional[datetime] = None) -> Dict:
        now = now or datetime.now(timezone.utc)
        periods = {
            'daily': now - timedelta(days=1),
            'weekly': now - timedelta(days=7),
            'monthly': now - timedelta(days=30),
        }
        summary = {'open_positions': len(self.get_open_positions()), 'daily_pnl': 0.0, 'weekly_pnl': 0.0, 'monthly_pnl': 0.0}
        with self.connect() as connection:
            for key, cutoff in periods.items():
                row = connection.execute(
                    'SELECT COALESCE(SUM(pnl), 0) AS pnl FROM trades WHERE status = ? AND closed_at >= ?',
                    ('closed', cutoff.isoformat()),
                ).fetchone()
                summary[f'{key}_pnl'] = float(row['pnl']) if row else 0.0
        return summary
