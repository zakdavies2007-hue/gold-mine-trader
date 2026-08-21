# Gold Mine Trader

A paper-trading system that detects high-probability entry opportunities using
technical analysis, news sentiment (FinBERT), and catalyst keyword scoring.

---

## Quick Start

```bash
git clone https://github.com/zakdavies2007-hue/gold-mine-trader.git
cd gold-mine-trader
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your settings (leave DRY_RUN=true to start)
python autotrader.py
```

---

## Detector Modes

### Full Mode (all providers available)
Requires: a valid `NEWS_API_KEY` *and* FinBERT loaded (`DISABLE_FINBERT=false`).

In full mode, signals are scored on three components:
- **Sentiment** – FinBERT transformer applied to news headlines (35%)
- **Catalysts** – keyword matching in headlines (30%)
- **Technical** – moving averages, RSI, volume spike (35%)

Signals scoring above `GOLD_MINE_THRESHOLD` are eligible for execution.

### Degraded Mode
If any provider is unavailable (no `NEWS_API_KEY`, FinBERT fails to load,
insufficient price data), the detector marks the result as **degraded**.

> **Degraded signals are never executed**, regardless of their score.
> The `eligible=False` flag and `degraded_providers` list identify which
> providers failed.  This prevents a neutral 0.5 sentiment placeholder
> from falsely contributing to an executable signal.

---

## Order Reconciliation

On startup and each scan cycle, the autotrader reconciles any pending/submitted
local intents against the broker:

| Broker status                             | Local action                          |
|-------------------------------------------|---------------------------------------|
| `filled`                                  | Mark open; update fill price/qty      |
| `accepted` / `new` / `pending_new` / ...  | Leave as submitted (retry next cycle) |
| `canceled` / `rejected` / `expired`       | Mark terminal; no position opened     |
| No broker order (intent was `submitted`)  | Mark terminal (network failure path)  |
| No broker order (intent was `pending`)    | Leave; process may not have submitted |

---

## Position Exits

Exit conditions are evaluated **continuously, including outside market hours**.
Stop-loss, take-profit, and time-based exits are issued as local REST sell
orders via Alpaca.

> **Important:** These are local REST orders, not broker-native stop orders.
> If the process is not running, exits will not fire.  Consider using
> Alpaca's native stop-loss orders for hard protection.

---

## Dashboard

```bash
# Access at http://127.0.0.1:8000 after starting the autotrader
```

> **Warning:** The dashboard has **no built-in authentication**.  It binds
> to loopback (`127.0.0.1`) by default.  Do not expose it on a public
> interface without an authentication proxy (e.g. nginx with HTTP Basic Auth).

---

## Environment Variables

See `.env.example` for the full list.  Key variables:

| Variable                  | Default                              | Notes                                         |
|---------------------------|--------------------------------------|-----------------------------------------------|
| `DRY_RUN`                 | `true`                               | Set `false` for live trading                  |
| `ALPACA_BASE_URL`         | `https://paper-api.alpaca.markets`   | Exact approved hostname required              |
| `NEWS_API_KEY`            | *(empty)*                            | Leave empty for technical-only mode           |
| `DISABLE_FINBERT`         | `false`                              | Set `true` to skip model loading              |
| `MAX_DAILY_LOSS_PERCENT`  | `0.05`                               | Positive fraction (0.05 = 5% loss limit)      |
| `DATABASE_PATH`           | `trading.db`                         | SQLite file; parent dir created automatically |
| `DASHBOARD_HOST`          | `127.0.0.1`                          | Loopback only in production                   |

---

## Running Tests

```bash
python -m unittest discover -s tests -v
```

Tests run offline without a `.env` file and without network access.

---

## Safety Constraints

- `DRY_RUN=true` by default; no real orders without explicit opt-in.
- Broker URL must be exact HTTPS Alpaca hostname.
- Degraded signals (failed providers) are never executed.
- Daily loss circuit-breaker stops new positions when limit is reached.
- Exits are local REST calls, not broker-native stops (see note above).
