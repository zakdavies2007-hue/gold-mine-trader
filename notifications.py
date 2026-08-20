from __future__ import annotations

import json
import logging
import smtplib
from email.message import EmailMessage
from typing import Dict, Optional

import requests

from trading_config import TradingConfig

LOGGER = logging.getLogger(__name__)


class NotificationManager:
    def __init__(self, config: TradingConfig, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()

    def send(self, subject: str, message: str):
        self._send_discord(subject, message)
        self._send_telegram(subject, message)
        self._send_email(subject, message)

    def send_trade_alert(self, trade: Dict):
        self.send(
            f"Trade {trade['symbol']} {trade['side'].upper()}",
            json.dumps(trade, indent=2, default=str),
        )

    def _send_discord(self, subject: str, message: str):
        if not self.config.discord_webhook:
            return
        try:
            self.session.post(self.config.discord_webhook, json={'content': f'**{subject}**\n```{message[:1500]}```'}, timeout=10)
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            LOGGER.warning('Discord notification failed: %s', exc)

    def _send_telegram(self, subject: str, message: str):
        if not self.config.telegram_token or not self.config.telegram_chat_id:
            return
        try:
            self.session.post(
                f'https://api.telegram.org/bot{self.config.telegram_token}/sendMessage',
                json={'chat_id': self.config.telegram_chat_id, 'text': f'{subject}\n{message[:3500]}'},
                timeout=10,
            )
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            LOGGER.warning('Telegram notification failed: %s', exc)

    def _send_email(self, subject: str, message: str):
        if not self.config.email_alerts or not self.config.email_address or not self.config.email_password:
            return
        email = EmailMessage()
        email['Subject'] = subject
        email['From'] = self.config.email_address
        email['To'] = self.config.email_address
        email.set_content(message)
        try:
            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                smtp.login(self.config.email_address, self.config.email_password)
                smtp.send_message(email)
        except OSError as exc:  # pragma: no cover - network dependent
            LOGGER.warning('Email notification failed: %s', exc)
