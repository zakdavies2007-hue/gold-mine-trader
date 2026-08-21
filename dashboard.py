"""
dashboard.py – Minimal HTTP dashboard for the trading system.

Security notes
--------------
* Binds to 127.0.0.1 by default.
* Security headers are set on every response (CSP, X-Content-Type-Options,
  X-Frame-Options, Cache-Control).
* The dashboard has NO built-in authentication.  Do not expose it on a public
  interface without an external authentication proxy.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

log = logging.getLogger(__name__)

_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Gold Mine Trader Dashboard</title>
<style>
body{{font-family:monospace;background:#111;color:#eee;padding:2em}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #444;padding:.4em .8em;text-align:left}}
th{{background:#222}}
.pos{{color:#4f4}}
.neg{{color:#f44}}
</style>
</head>
<body>
<h1>Gold Mine Trader</h1>
<p><em>Note: this dashboard has no authentication. Do not expose it publicly.</em></p>
<h2>Summary</h2>
<pre>{summary}</pre>
<h2>Open Positions</h2>
{positions_table}
<h2>Recent Trades</h2>
{trades_table}
</body>
</html>
"""


def _html_table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "<p>None</p>"
    header = "".join(f"<th>{c}</th>" for c in cols)
    body_rows = []
    for r in rows:
        cells = []
        for c in cols:
            val = r.get(c, "")
            if isinstance(val, float):
                val = f"{val:.4f}"
            cell = f"<td>{val}</td>"
            cells.append(cell)
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><tr>{header}</tr>{''.join(body_rows)}</table>"


class DashboardHandler(BaseHTTPRequestHandler):
    """Request handler for the trading dashboard."""

    # set by DashboardServer
    _trade_store: Any = None

    def _write_response(
        self,
        status: int,
        content_type: str,
        body: bytes,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        try:
            if path == "/":
                self._serve_html()
            elif path == "/api/summary":
                self._serve_json(self._trade_store.performance_summary())
            elif path == "/api/positions":
                self._serve_json(self._trade_store.get_open_positions())
            elif path == "/api/trades":
                self._serve_json(self._trade_store.get_recent_trades(50))
            else:
                self._write_response(404, "text/plain", b"Not Found")
        except Exception as exc:
            log.error("Dashboard handler error: %s", exc)
            self._write_response(
                500, "application/json",
                json.dumps({"error": str(exc)}).encode()
            )

    def _serve_json(self, data: Any) -> None:
        body = json.dumps(data, default=str).encode()
        self._write_response(200, "application/json", body)

    def _serve_html(self) -> None:
        summary = self._trade_store.performance_summary()
        positions = self._trade_store.get_open_positions()
        trades = self._trade_store.get_recent_trades(20)

        pos_cols = ["symbol", "entry_side", "entry_price", "entry_qty", "stop_loss",
                    "take_profit", "opened_at"]
        trade_cols = ["symbol", "entry_side", "entry_price", "exit_price", "pnl",
                      "exit_reason", "opened_at", "closed_at"]

        html = _HTML_TEMPLATE.format(
            summary=json.dumps(summary, indent=2, default=str),
            positions_table=_html_table(positions, pos_cols),
            trades_table=_html_table(trades, trade_cols),
        )
        self._write_response(200, "text/html; charset=utf-8", html.encode())

    def log_message(self, fmt: str, *args) -> None:  # type: ignore[override]
        log.debug("Dashboard: " + fmt, *args)


class DashboardServer:
    """Wraps ThreadingHTTPServer with clean lifecycle management."""

    def __init__(
        self,
        trade_store: Any,
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        self._store = trade_store
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the dashboard server in a daemon thread."""
        # Inject the store into the handler class for this server
        store = self._store

        class _Handler(DashboardHandler):
            _trade_store = store

        self._server = ThreadingHTTPServer((self._host, self._port), _Handler)
        self._server.allow_reuse_address = True
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="dashboard-server",
        )
        self._thread.start()
        log.info("Dashboard started at http://%s:%d", self._host, self._port)

    def stop(self) -> None:
        """Shut down the server gracefully."""
        if self._server:
            self._server.shutdown()
            log.info("Dashboard stopped")
