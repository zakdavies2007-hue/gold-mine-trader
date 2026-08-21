"""
alpaca_broker.py – Alpaca broker integration with safety guardrails.

Key safety properties
---------------------
* URL must be HTTPS, must match an approved Alpaca hostname exactly, and must
  not contain embedded credentials or query-string parameters.
* Order side must be "buy" or "sell".
* In dry-run mode no HTTP request is ever made.
* All guardrail violations raise BrokerGuardrailError, a distinct exception
  type that callers can catch separately from network or logic errors.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Any

import requests

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Approved Alpaca hostname set (exact match, no wildcards)
# ---------------------------------------------------------------------------
_APPROVED_HOSTS = frozenset(
    {
        "paper-api.alpaca.markets",
        "api.alpaca.markets",
        "broker-api.alpaca.markets",
    }
)

VALID_ORDER_SIDES = frozenset({"buy", "sell"})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BrokerGuardrailError(Exception):
    """Raised when a safety check prevents an operation."""


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


def _validate_url(url: str) -> None:
    """Raise BrokerGuardrailError if *url* fails safety checks."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise BrokerGuardrailError(f"Malformed broker URL: {exc}") from exc

    if parsed.scheme != "https":
        raise BrokerGuardrailError(
            f"Broker URL must use HTTPS; got scheme {parsed.scheme!r}"
        )

    # Reject embedded credentials (user:pass@host)
    if parsed.username or parsed.password:
        raise BrokerGuardrailError(
            "Broker URL must not contain embedded credentials"
        )

    # Exact hostname check – prevents look-alike or proxy endpoints
    host = parsed.hostname or ""
    if host not in _APPROVED_HOSTS:
        raise BrokerGuardrailError(
            f"Broker hostname {host!r} is not an approved Alpaca endpoint. "
            f"Approved hosts: {sorted(_APPROVED_HOSTS)}"
        )

    # Reject query parameters or fragments in the base URL
    if parsed.query or parsed.fragment:
        raise BrokerGuardrailError(
            "Broker base URL must not contain query parameters or fragments"
        )


# ---------------------------------------------------------------------------
# Broker client
# ---------------------------------------------------------------------------


class AlpacaBroker:
    """Thin wrapper around the Alpaca REST API with built-in guardrails."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str,
        dry_run: bool = True,
        timeout: int = 10,
    ) -> None:
        _validate_url(base_url)
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_url = base_url.rstrip("/")
        self.dry_run = dry_run
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self._base_url}{path}"
        for attempt in range(3):
            try:
                resp = self._session.get(url, params=params, timeout=self._timeout)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                    log.warning("Rate-limited; waiting %s s before retry", retry_after)
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                if attempt == 2:
                    raise
                log.warning("GET %s attempt %d failed: %s", path, attempt + 1, exc)
                time.sleep(2 ** attempt)
        return None  # unreachable

    def _post(self, path: str, body: dict) -> Any:
        url = f"{self._base_url}{path}"
        for attempt in range(3):
            try:
                resp = self._session.post(url, json=body, timeout=self._timeout)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                    log.warning("Rate-limited; waiting %s s before retry", retry_after)
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                if attempt == 2:
                    raise
                log.warning("POST %s attempt %d failed: %s", path, attempt + 1, exc)
                time.sleep(2 ** attempt)
        return None  # unreachable

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_account(self) -> dict:
        """Return account information."""
        if self.dry_run:
            return {"status": "ACTIVE", "cash": "0", "equity": "0", "mode": "dry_run"}
        return self._get("/v2/account")

    def list_positions(self) -> list[dict]:
        """Return all open broker positions."""
        if self.dry_run:
            return []
        return self._get("/v2/positions") or []

    def get_order_by_client_id(self, client_order_id: str) -> dict | None:
        """Fetch a broker order by URL-encoded client_order_id.

        Returns None if the order does not exist (404).
        """
        if self.dry_run:
            return None
        encoded = urllib.parse.quote(client_order_id, safe="")
        try:
            return self._get(f"/v2/orders:by_client_order_id",
                             params={"client_order_id": client_order_id})
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise

    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "market",
        time_in_force: str = "day",
        client_order_id: str | None = None,
    ) -> dict:
        """Submit an order.  Raises BrokerGuardrailError for invalid inputs."""
        side = side.lower()
        if side not in VALID_ORDER_SIDES:
            raise BrokerGuardrailError(
                f"Order side must be 'buy' or 'sell'; got {side!r}"
            )
        if not isinstance(qty, int) or qty <= 0:
            raise BrokerGuardrailError(
                f"Order quantity must be a positive integer; got {qty!r}"
            )

        body: dict[str, Any] = {
            "symbol": symbol.upper(),
            "qty": qty,
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id

        if self.dry_run:
            log.info(
                "[DRY-RUN] Order not submitted: %s %d %s @ %s",
                side,
                qty,
                symbol,
                order_type,
            )
            return {
                "id": "dry-run",
                "client_order_id": client_order_id or "",
                "status": "accepted",
                "symbol": symbol.upper(),
                "qty": str(qty),
                "side": side,
                "mode": "dry_run",
            }

        log.info("Submitting order: %s %d %s", side, qty, symbol)
        result = self._post("/v2/orders", body)
        log.info(
            "Order submitted: id=%s status=%s",
            result.get("id"),
            result.get("status"),
        )
        return result
