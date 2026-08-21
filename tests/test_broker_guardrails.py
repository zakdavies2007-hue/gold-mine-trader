"""
tests/test_broker_guardrails.py – Broker URL, side, and dry-run guardrail tests.
"""
import unittest

from alpaca_broker import AlpacaBroker, BrokerGuardrailError, _validate_url, VALID_ORDER_SIDES


class TestValidateUrl(unittest.TestCase):

    def test_valid_paper_url(self):
        _validate_url("https://paper-api.alpaca.markets")  # no exception

    def test_valid_live_url(self):
        _validate_url("https://api.alpaca.markets")

    def test_valid_broker_url(self):
        _validate_url("https://broker-api.alpaca.markets")

    def test_rejects_http(self):
        with self.assertRaises(BrokerGuardrailError):
            _validate_url("http://paper-api.alpaca.markets")

    def test_rejects_unknown_host(self):
        with self.assertRaises(BrokerGuardrailError):
            _validate_url("https://evil.alpaca.markets.example.com")

    def test_rejects_lookalike(self):
        with self.assertRaises(BrokerGuardrailError):
            _validate_url("https://paper-api.alpaca.markets.evil.com")

    def test_rejects_embedded_credentials(self):
        with self.assertRaises(BrokerGuardrailError):
            _validate_url("******paper-api.alpaca.markets")

    def test_rejects_query_params(self):
        with self.assertRaises(BrokerGuardrailError):
            _validate_url("https://paper-api.alpaca.markets?foo=bar")

    def test_rejects_fragment(self):
        with self.assertRaises(BrokerGuardrailError):
            _validate_url("https://paper-api.alpaca.markets#section")

    def test_rejects_empty_string(self):
        with self.assertRaises(BrokerGuardrailError):
            _validate_url("")


class TestAlpacaBrokerDryRun(unittest.TestCase):

    def _make(self):
        return AlpacaBroker(
            api_key="key",
            secret_key="secret",
            base_url="https://paper-api.alpaca.markets",
            dry_run=True,
        )

    def test_dry_run_get_account(self):
        b = self._make()
        acc = b.get_account()
        self.assertEqual(acc["mode"], "dry_run")

    def test_dry_run_no_real_request(self):
        """Dry-run submit_order must not make any HTTP request."""
        import unittest.mock as mock
        b = self._make()
        with mock.patch("requests.Session.post") as mock_post:
            result = b.submit_order("AAPL", 5, "buy", client_order_id="test-1")
        mock_post.assert_not_called()
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["side"], "buy")

    def test_dry_run_submit_returns_accepted(self):
        b = self._make()
        result = b.submit_order("AAPL", 1, "buy")
        self.assertEqual(result["status"], "accepted")

    def test_valid_order_sides(self):
        self.assertIn("buy", VALID_ORDER_SIDES)
        self.assertIn("sell", VALID_ORDER_SIDES)

    def test_invalid_side_raises(self):
        b = self._make()
        with self.assertRaises(BrokerGuardrailError):
            b.submit_order("AAPL", 1, "long")

    def test_zero_quantity_raises(self):
        b = self._make()
        with self.assertRaises(BrokerGuardrailError):
            b.submit_order("AAPL", 0, "buy")

    def test_negative_quantity_raises(self):
        b = self._make()
        with self.assertRaises(BrokerGuardrailError):
            b.submit_order("AAPL", -1, "buy")

    def test_sell_side_accepted(self):
        b = self._make()
        result = b.submit_order("AAPL", 1, "sell")
        self.assertEqual(result["side"], "sell")

    def test_list_positions_dry_run(self):
        b = self._make()
        self.assertEqual(b.list_positions(), [])

    def test_get_order_by_client_id_dry_run(self):
        b = self._make()
        self.assertIsNone(b.get_order_by_client_id("test-id"))


if __name__ == "__main__":
    unittest.main()
