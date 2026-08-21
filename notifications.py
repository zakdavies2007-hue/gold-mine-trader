"""
notifications.py – Multi-channel notification manager.

Channels: Discord webhook, Telegram Bot API, SMTP email.
All channels are optional and gated by configuration flags.
Failures are logged but never propagate to the caller.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any

import requests

log = logging.getLogger(__name__)

_MAX_MSG_LEN = 1900  # Discord limit is 2000; leave headroom


def _truncate(text: str, limit: int = _MAX_MSG_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n…[truncated]"


class NotificationManager:
    """Send notifications via Discord, Telegram, and/or email."""

    def __init__(
        self,
        discord_webhook: str = "",
        discord_alerts: bool = False,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        telegram_alerts: bool = False,
        email_alerts: bool = False,
        email_address: str = "",
        email_password: str = "",
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587,
        timeout: int = 10,
    ) -> None:
        self.discord_webhook = discord_webhook
        self.discord_alerts = discord_alerts and bool(discord_webhook)
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.telegram_alerts = telegram_alerts and bool(telegram_token) and bool(telegram_chat_id)
        self.email_alerts = email_alerts and bool(email_address)
        self.email_address = email_address
        self.email_password = email_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.timeout = timeout

    # ------------------------------------------------------------------

    def send(self, subject: str, body: str) -> dict[str, bool]:
        """Send a notification on all configured channels.

        Returns a dict mapping channel name to success flag.
        """
        results: dict[str, bool] = {}
        if self.discord_alerts:
            results["discord"] = self._send_discord(subject, body)
        if self.telegram_alerts:
            results["telegram"] = self._send_telegram(subject, body)
        if self.email_alerts:
            results["email"] = self._send_email(subject, body)
        return results

    # ------------------------------------------------------------------

    def _send_discord(self, subject: str, body: str) -> bool:
        import re
        # Escape backtick sequences that could corrupt the code block
        safe_body = re.sub(r"`{3,}", "```", body)
        content = _truncate(f"**{subject}**\n```\n{safe_body}\n```")
        try:
            resp = requests.post(
                self.discord_webhook,
                json={"content": content},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except requests.HTTPError as exc:
            log.warning("Discord notification failed (HTTP %s): %s",
                        exc.response.status_code if exc.response else "?", exc)
            return False
        except Exception as exc:
            log.warning("Discord notification error: %s", exc)
            return False

    def _send_telegram(self, subject: str, body: str) -> bool:
        text = _truncate(f"*{subject}*\n{body}", limit=4000)
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except requests.HTTPError as exc:
            log.warning("Telegram notification failed (HTTP %s): %s",
                        exc.response.status_code if exc.response else "?", exc)
            return False
        except Exception as exc:
            log.warning("Telegram notification error: %s", exc)
            return False

    def _send_email(self, subject: str, body: str) -> bool:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.email_address
        msg["To"] = self.email_address
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout) as smtp:
                smtp.starttls()
                smtp.login(self.email_address, self.email_password)
                smtp.sendmail(self.email_address, [self.email_address], msg.as_string())
            return True
        except smtplib.SMTPException as exc:
            log.warning("Email SMTP error: %s", exc)
            return False
        except OSError as exc:
            log.warning("Email OS error: %s", exc)
            return False
        except Exception as exc:
            log.warning("Email notification error: %s", exc)
            return False

    @classmethod
    def from_config(cls, config: Any) -> "NotificationManager":
        """Construct from a TradingConfig instance."""
        return cls(
            discord_webhook=getattr(config, "discord_webhook", ""),
            discord_alerts=getattr(config, "discord_alerts", False),
            telegram_token=getattr(config, "telegram_token", ""),
            telegram_chat_id=getattr(config, "telegram_chat_id", ""),
            telegram_alerts=getattr(config, "telegram_alerts", False),
            email_alerts=getattr(config, "email_alerts", False),
            email_address=getattr(config, "email_address", ""),
            email_password=getattr(config, "email_password", ""),
            smtp_server=getattr(config, "smtp_server", "smtp.gmail.com"),
            smtp_port=getattr(config, "smtp_port", 587),
        )
