from __future__ import annotations

import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List

from trade_store import TradeStore


class DashboardServer:
    def __init__(self, store: TradeStore, host: str = '127.0.0.1', port: int = 8000):
        self.store = store
        self.host = host
        self.port = port

    def payload(self) -> Dict:
        return {
            'summary': self.store.performance_summary(),
            'positions': self.store.get_open_positions(),
            'recent_trades': self.store.get_recent_trades(20),
        }

    def render_html(self) -> str:
        payload = self.payload()
        summary = payload['summary']
        positions = payload['positions']
        trades = payload['recent_trades']

        def rows(items: List[Dict], columns: List[str]) -> str:
            if not items:
                return '<tr><td colspan="{}">No data</td></tr>'.format(len(columns))
            rendered = []
            for item in items:
                rendered.append('<tr>{}</tr>'.format(''.join(f'<td>{html.escape(str(item.get(column, "")))}</td>' for column in columns)))
            return ''.join(rendered)

        return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>Gold Mine Trader Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; padding: 1rem; background: #0f172a; color: #e2e8f0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-bottom: 1rem; }}
    .card {{ background: #1e293b; border-radius: 12px; padding: 1rem; }}
    table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; }}
    th, td {{ padding: 0.6rem; text-align: left; border-bottom: 1px solid #334155; font-size: 0.92rem; }}
    a {{ color: #38bdf8; }}
  </style>
</head>
<body>
  <h1>Gold Mine Trader</h1>
  <p>Read-only dashboard. Refresh the page to update values.</p>
  <div class='grid'>
    <div class='card'><strong>Daily P&amp;L</strong><br>{summary['daily_pnl']:.2f}</div>
    <div class='card'><strong>Weekly P&amp;L</strong><br>{summary['weekly_pnl']:.2f}</div>
    <div class='card'><strong>Monthly P&amp;L</strong><br>{summary['monthly_pnl']:.2f}</div>
    <div class='card'><strong>Open Positions</strong><br>{summary['open_positions']}</div>
  </div>
  <h2>Open Positions</h2>
  <table>
    <tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Stop</th><th>Target</th><th>Opened</th></tr>
    {rows(positions, ['symbol', 'quantity', 'entry_price', 'stop_loss', 'take_profit', 'opened_at'])}
  </table>
  <h2>Recent Trades</h2>
  <table>
    <tr><th>Symbol</th><th>Status</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&amp;L</th></tr>
    {rows(trades, ['symbol', 'status', 'quantity', 'entry_price', 'exit_price', 'pnl'])}
  </table>
  <p><a href='/api/summary'>API summary</a></p>
</body>
</html>"""

    def create_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == '/api/summary':
                    self._json(server.payload())
                    return
                if self.path == '/api/positions':
                    self._json(server.store.get_open_positions())
                    return
                if self.path == '/api/trades':
                    self._json(server.store.get_recent_trades(50))
                    return
                if self.path in {'/', '/index.html'}:
                    body = server.render_html().encode('utf-8')
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def do_POST(self):  # noqa: N802
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

            def _json(self, payload):
                body = json.dumps(payload, default=str).encode('utf-8')
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        return Handler

    def serve_forever(self):
        ThreadingHTTPServer((self.host, self.port), self.create_handler()).serve_forever()
