"""
tests/test_notifications.py – NotificationManager tests (no real network calls).
"""
import smtplib
import unittest
import unittest.mock as mock
from unittest.mock import MagicMock, patch

import requests

from notifications import NotificationManager, _truncate


class TestTruncate(unittest.TestCase):

    def test_short_string_unchanged(self):
        self.assertEqual(_truncate("hello", 50), "hello")

    def test_long_string_truncated(self):
        text = "x" * 2000
        result = _truncate(text, 100)
        self.assertLessEqual(len(result), 100)
        self.assertIn("truncated", result)


class TestNotificationManagerSend(unittest.TestCase):

    def _make(self, **kw):
        defaults = dict(
            discord_webhook="https://discord.example.com/webhook",
            discord_alerts=True,
            telegram_token="token123",
            telegram_chat_id="chat123",
            telegram_alerts=True,
            email_alerts=True,
            email_address="test@example.com",
            email_password="pw",
        )
        defaults.update(kw)
        return NotificationManager(**defaults)

    def test_send_discord_success(self):
        nm = self._make(telegram_alerts=False, email_alerts=False)
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = nm.send("Test Subject", "Test body")
        self.assertTrue(result.get("discord"))
        mock_post.assert_called_once()

    def test_send_discord_http_error(self):
        nm = self._make(telegram_alerts=False, email_alerts=False)
        mock_resp = MagicMock(status_code=401)
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        with patch("requests.post", return_value=mock_resp):
            result = nm.send("Test", "Body")
        self.assertFalse(result.get("discord"))

    def test_send_telegram_success(self):
        nm = self._make(discord_alerts=False, email_alerts=False)
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        with patch("requests.post", return_value=mock_resp):
            result = nm.send("Test", "Body")
        self.assertTrue(result.get("telegram"))

    def test_send_telegram_failure(self):
        nm = self._make(discord_alerts=False, email_alerts=False)
        with patch("requests.post", side_effect=requests.RequestException("fail")):
            result = nm.send("Test", "Body")
        self.assertFalse(result.get("telegram"))

    def test_send_email_success(self):
        nm = self._make(discord_alerts=False, telegram_alerts=False)
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = lambda s: s
        mock_smtp.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=mock_smtp):
            result = nm.send("Subject", "Body")
        self.assertTrue(result.get("email"))

    def test_send_email_smtp_error(self):
        nm = self._make(discord_alerts=False, telegram_alerts=False)
        with patch("smtplib.SMTP", side_effect=smtplib.SMTPException("fail")):
            result = nm.send("Subject", "Body")
        self.assertFalse(result.get("email"))

    def test_no_channels_enabled(self):
        nm = NotificationManager()
        result = nm.send("Test", "Body")
        self.assertEqual(result, {})

    def test_discord_disabled_without_webhook(self):
        nm = NotificationManager(discord_alerts=True, discord_webhook="")
        with patch("requests.post") as mock_post:
            nm.send("Test", "Body")
        mock_post.assert_not_called()

    def test_all_channels_called(self):
        nm = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = lambda s: s
        mock_smtp.__exit__ = MagicMock(return_value=False)
        with patch("requests.post", return_value=mock_resp), \
             patch("smtplib.SMTP", return_value=mock_smtp):
            result = nm.send("Subject", "Body")
        self.assertIn("discord", result)
        self.assertIn("telegram", result)
        self.assertIn("email", result)


class TestFromConfig(unittest.TestCase):

    def test_from_config_uses_attrs(self):
        cfg = MagicMock()
        cfg.discord_webhook = "https://wh.example.com"
        cfg.discord_alerts = True
        cfg.telegram_token = ""
        cfg.telegram_chat_id = ""
        cfg.telegram_alerts = False
        cfg.email_alerts = False
        cfg.email_address = ""
        cfg.email_password = ""
        cfg.smtp_server = "smtp.example.com"
        cfg.smtp_port = 587
        nm = NotificationManager.from_config(cfg)
        self.assertTrue(nm.discord_alerts)
        self.assertFalse(nm.telegram_alerts)


if __name__ == "__main__":
    unittest.main()
