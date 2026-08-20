from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import requests

from trading_config import LIVE_TRADING_ACK, TradingConfig

LOGGER = logging.getLogger(__name__)


class BrokerGuardrailError(RuntimeError):
    pass


class AlpacaBroker:
    def __init__(self, config: TradingConfig, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()

    def validate_mode(self):
        if self.config.trading_mode not in {'paper', 'live'}:
            raise BrokerGuardrailError('TRADING_MODE must be either paper or live.')
        if self.config.trading_mode == 'paper' and 'paper-api.alpaca.markets' not in self.config.alpaca_base_url:
            raise BrokerGuardrailError('Paper mode requires the Alpaca paper API base URL.')
        if self.config.trading_mode == 'live':
            if not self.config.enable_live_trading:
                raise BrokerGuardrailError('Live trading is disabled unless ENABLE_LIVE_TRADING=true.')
            if self.config.live_trading_acknowledgement != LIVE_TRADING_ACK:
                raise BrokerGuardrailError('Live trading requires an explicit acknowledgement phrase.')
            if 'paper-api.alpaca.markets' in self.config.alpaca_base_url:
                raise BrokerGuardrailError('Live trading cannot use the paper API base URL.')

    def validate_credentials(self):
        if not self.config.alpaca_api_key or not self.config.alpaca_secret_key:
            raise BrokerGuardrailError('Alpaca credentials are required before order execution is enabled.')

    def _headers(self) -> Dict[str, str]:
        return {
            'APCA-API-KEY-ID': self.config.alpaca_api_key,
            'APCA-API-SECRET-KEY': self.config.alpaca_secret_key,
            'Content-Type': 'application/json',
        }

    def _request(self, method: str, path: str, *, json_payload: Optional[Dict] = None) -> Dict:
        self.validate_mode()
        self.validate_credentials()
        last_error = None
        for delay in (0, 1, 2):
            if delay:
                time.sleep(delay)
            try:
                response = self.session.request(
                    method,
                    f'{self.config.alpaca_base_url}{path}',
                    headers=self._headers(),
                    json=json_payload,
                    timeout=10,
                )
                if response.status_code >= 500 or response.status_code == 429:
                    last_error = BrokerGuardrailError(f'Alpaca temporary error: {response.status_code} {response.text}')
                    continue
                response.raise_for_status()
                return response.json() if response.content else {}
            except requests.RequestException as exc:
                last_error = exc
        raise BrokerGuardrailError(f'Alpaca request failed after retries: {last_error}')

    def get_account(self) -> Dict:
        if self.config.dry_run:
            return {
                'equity': str(self.config.starting_capital),
                'buying_power': str(self.config.starting_capital),
                'status': 'DRY_RUN',
                'trading_mode': self.config.trading_mode,
            }
        return self._request('GET', '/v2/account')

    def list_positions(self):
        if self.config.dry_run:
            return []
        return self._request('GET', '/v2/positions')

    def submit_order(self, *, symbol: str, qty: int, side: str, client_order_id: str) -> Dict:
        if qty <= 0:
            raise BrokerGuardrailError('Order quantity must be positive.')
        self.validate_mode()
        if self.config.dry_run:
            return {
                'id': f'dry-run-{client_order_id}',
                'symbol': symbol,
                'qty': str(qty),
                'side': side,
                'status': 'accepted',
                'client_order_id': client_order_id,
                'mode': 'dry_run',
            }
        payload = {
            'symbol': symbol,
            'qty': qty,
            'side': side,
            'type': 'market',
            'time_in_force': 'day',
            'client_order_id': client_order_id,
        }
        result = self._request('POST', '/v2/orders', json_payload=payload)
        LOGGER.info('Submitted %s order for %s (%s)', side, symbol, client_order_id)
        return result
