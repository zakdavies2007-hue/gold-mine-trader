import io
import json
import unittest

from dashboard import DashboardServer
from trade_store import TradeStore


class NonClosingBytesIO(io.BytesIO):
    def close(self):
        pass


class FakeSocket:
    def __init__(self, request_bytes: bytes):
        self._rfile = io.BytesIO(request_bytes)
        self._wfile = NonClosingBytesIO()

    def makefile(self, mode, *args, **kwargs):
        if 'r' in mode:
            return self._rfile
        return self._wfile

    def sendall(self, data):
        self._wfile.write(data)

    def close(self):
        pass


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.store = TradeStore(':memory:')
        self.server = DashboardServer(self.store)

    def _request(self, path: str):
        handler_cls = self.server.create_handler()
        request = f'GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n'.encode('utf-8')
        sock = FakeSocket(request)
        handler_cls(sock, ('127.0.0.1', 12345), object())
        raw = sock._wfile.getvalue().decode('utf-8')
        header_text, body = raw.split('\r\n\r\n', 1)
        lines = header_text.split('\r\n')
        status_line = lines[0]
        headers = {}
        for line in lines[1:]:
            if ': ' in line:
                key, value = line.split(': ', 1)
                headers[key] = value
        return status_line, headers, body

    def test_api_summary_returns_json(self):
        status, headers, body = self._request('/api/summary')
        self.assertIn('200', status)
        self.assertEqual(headers['Content-Type'], 'application/json')
        payload = json.loads(body)
        self.assertIn('summary', payload)
        self.assertIn('positions', payload)
        self.assertIn('recent_trades', payload)

    def test_unknown_route_returns_json_404(self):
        status, headers, body = self._request('/missing')
        self.assertIn('404', status)
        self.assertEqual(headers['Content-Type'], 'application/json')
        payload = json.loads(body)
        self.assertIn('error', payload)

    def test_security_headers_present(self):
        status, headers, body = self._request('/api/summary')
        self.assertIn('200', status)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
