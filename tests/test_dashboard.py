"""
tests/test_dashboard.py – Dashboard server tests (no real network).
"""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest

from dashboard import DashboardServer
from trade_store import TradeStore


class TestDashboardServer(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.store = TradeStore(self._tmp.name)
        # Add some data
        self.store.open_trade("AAPL", "dash-1", "buy", 150.0, 2)
        self.store.close_trade("dash-1", 160.0, 2, exit_reason="take_profit")
        # Use port 0 to let OS pick a free port, then retrieve it
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = DashboardServer(self.store, host="127.0.0.1", port=self.port)
        self.server.start()
        time.sleep(0.3)

    def tearDown(self):
        self.server.stop()
        os.unlink(self._tmp.name)

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        # Normalise header keys to title-case for consistent lookup
        headers = {k.title(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, headers, body

    def test_root_returns_200(self):
        status, _, _ = self._get("/")
        self.assertEqual(status, 200)

    def test_root_content_type_html(self):
        _, headers, _ = self._get("/")
        ct = headers.get("Content-Type", "")
        self.assertIn("text/html", ct)

    def test_security_header_csp(self):
        _, headers, _ = self._get("/")
        self.assertIn("Content-Security-Policy", headers)

    def test_security_header_nosniff(self):
        _, headers, _ = self._get("/")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_security_header_no_store(self):
        _, headers, _ = self._get("/")
        self.assertIn("no-store", headers.get("Cache-Control", ""))

    def test_api_summary_returns_json(self):
        status, headers, body = self._get("/api/summary")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("total_trades", data)

    def test_api_trades_returns_json(self):
        status, _, body = self._get("/api/trades")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIsInstance(data, list)

    def test_api_positions_returns_json(self):
        status, _, body = self._get("/api/positions")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIsInstance(data, list)

    def test_unknown_path_returns_404(self):
        status, _, _ = self._get("/unknown/path")
        self.assertEqual(status, 404)

    def test_html_contains_warning_text(self):
        _, _, body = self._get("/")
        self.assertIn(b"no authentication", body)


if __name__ == "__main__":
    unittest.main()
