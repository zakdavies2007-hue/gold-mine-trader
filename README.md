# Gold Mine Trader

Gold Mine Trader is a paper-trading-first automation layer around the existing detector logic from the notebook. It keeps the detector/configuration shape compatible while adding:

- scheduled market-hours scanning
- Alpaca paper/live execution guardrails
- stop-loss / take-profit position management
- volatility, momentum, trend, volume, and support/resistance research metrics
- SQLite trade and performance logging
- Discord / Telegram / email notifications
- a mobile-friendly read-only dashboard plus JSON API

## Safety defaults

- `TRADING_MODE=paper` by default
- `DRY_RUN=true` by default
- live trading is blocked unless all live-trading safeguards are explicitly enabled
- missing Alpaca credentials fail closed and prevent execution
- the dashboard is read-only and binds to `127.0.0.1` by default

This project does **not** claim or guarantee profitability.

## Repository layout

```text
/home/runner/work/gold-mine-trader/gold-mine-trader
├── gold_mine_trader.ipynb   # original notebook detector
├── gold_mine_trader.py      # extracted compatible detector module
├── autotrader.py            # market-hours scanner and execution loop
├── alpaca_broker.py         # Alpaca client with paper/live safeguards
├── position_manager.py      # stop-loss / take-profit / sizing logic
├── market_research.py       # volatility, momentum, trend, volume, S/R metrics
├── trade_store.py           # SQLite trade + scan persistence
├── dashboard.py             # read-only dashboard + JSON API
├── notifications.py         # Discord / Telegram / email dispatch
├── trading_config.py        # environment-driven runtime config
├── config.py
├── config_advanced.py
└── tests/
```

## Local setup

```bash
cd /home/runner/work/gold-mine-trader/gold-mine-trader
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and keep the defaults unless you intentionally want to change behavior:

```dotenv
TRADING_MODE=paper
DRY_RUN=true
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

## Running

### Detector-only compatibility

You can still use the extracted detector directly:

```bash
python - <<'PY'
from gold_mine_trader import GoldMineTrader
trader = GoldMineTrader(symbol='AAPL')
print(trader.scan_for_gold_mine())
PY
```

### Automated scanner / paper trader

```bash
python autotrader.py
```

Behavior:

1. validates market hours in `America/New_York`
2. scans configured symbols on the configured interval
3. records scans in SQLite
4. prevents duplicate orders on repeated scans
5. enforces max position count and daily-loss guardrails
6. places Alpaca paper orders only when credentials and safety checks allow
7. serves a read-only dashboard on `http://127.0.0.1:8000`

## Environment variables

Use `.env.example` as the source of truth. Key values:

- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`
- `TRADING_MODE=paper|live`
- `DRY_RUN=true|false`
- `ENABLE_LIVE_TRADING=true|false`
- `LIVE_TRADING_ACKNOWLEDGEMENT=I_UNDERSTAND_AND_ACCEPT_LIVE_TRADING_RISK`
- `DISCORD_WEBHOOK`
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
- `EMAIL_ALERTS`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`

### Live trading safeguards

Live trading remains disabled unless **all** of the following are true:

1. `TRADING_MODE=live`
2. `DRY_RUN=false`
3. `ENABLE_LIVE_TRADING=true`
4. `LIVE_TRADING_ACKNOWLEDGEMENT=I_UNDERSTAND_AND_ACCEPT_LIVE_TRADING_RISK`
5. `ALPACA_BASE_URL=https://api.alpaca.markets`
6. valid Alpaca credentials are present

If any requirement is missing, execution is blocked.

## Dashboard and API

Read-only routes:

- `/`
- `/api/summary`
- `/api/positions`
- `/api/trades`

The dashboard is designed to be usable from a phone browser, but it should not be exposed directly on the open internet.

### Safer phone access

Recommended deployment pattern:

1. keep `DASHBOARD_HOST=127.0.0.1`
2. publish it through a VPN or private tunnel such as Tailscale
3. if you use a reverse proxy, require HTTPS and authentication
4. do not expose write endpoints; the bundled dashboard is read-only
5. keep secrets in environment variables on the host, never in git

## Notifications

Notifications are optional. Missing webhook, bot, or email credentials simply disable that channel. Secrets must come from environment variables.

## Validation

Run the focused tests:

```bash
python -m unittest discover -s tests -v
```

## Disclaimer

- Trading can lose money.
- Past performance does not guarantee future results.
- Use paper trading before considering any live deployment.
- Review all safeguards yourself before enabling live execution.
