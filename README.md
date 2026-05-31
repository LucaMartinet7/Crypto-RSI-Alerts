# Crypto RSI Alerts

Telegram alerts for crypto **RSI** levels. It watches the live RSI of every
coin you list and pings you the moment one crosses your threshold — plus a
once-a-day summary.

## What you get

- 🔻 **Cross-under alert** — the instant a coin's RSI drops below the threshold
  (default 30 → "oversold").
- 🟢 **Cross-over alert** — the instant it climbs back above the threshold
  ("recovered").
- 🗓️ **Daily digest** (08:00 UTC by default) — two lists: everything currently
  oversold, and everything that recovered since the last digest.

RSI is read from the **live, in-progress candle**, so on the `1d` timeframe the
value still moves throughout the day as price moves — alerts aren't stuck
waiting for the daily close.

## File layout

```
Crypto-RSI-Alerts/
├── alerter/                  ← the engine (don't usually need to touch)
│   ├── __init__.py           what the package exposes
│   ├── indicators.py         rsi, sma, ema — the math
│   ├── notifier.py           Telegram / Console / Multi — where alerts go
│   ├── exchanges.py          builds + caches exchange connections
│   ├── watchlist.py          the Watchlist dataclass
│   └── monitor.py            the RSI band monitor (the heart of the app)
├── watchlists.py             ← what to monitor (edit this)
├── .env                      ← your settings + credentials (not committed)
├── .env.example              ← template
├── requirements.txt
├── run.py                    ← python3 run.py
└── README.md
```

## Install & run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

python3 run.py            # runs forever
python3 run.py --once     # one scan then exit (good for a quick test)
```

`.env` is read automatically — no `export` needed.

## Settings (.env)

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | your bot token |
| `TELEGRAM_CHAT_ID` | — | chat ID(s) to message (comma-separate for several) |
| `RSI_LENGTH` | `14` | RSI look-back period |
| `RSI_THRESHOLD` | `30` | the line that triggers oversold/recovered |
| `MONITOR_TIMEFRAME` | `1d` | candle size the RSI is computed on |
| `DIGEST_HOUR_UTC` | `8` | hour (UTC) the daily summary is sent |
| `MONITOR_INTERVAL` | `600` | seconds between scans |
| `LOG_LEVEL` | `INFO` | log verbosity |

## How to add things

### Watch more coins
Open `watchlists.py` and add the symbol to a watchlist's `symbols=[...]` list.

### Watch coins on another exchange
Append a new `Watchlist(...)` to `WATCHLISTS` in `watchlists.py`:

```python
Watchlist(
    name="kucoin-extra",
    exchange="kucoin",
    quote="USDT",
    symbols=["BTC", "ETH", "SOL"],
),
```

### Send alerts somewhere other than Telegram
Open `alerter/notifier.py` and subclass `Notifier`:

```python
class DiscordNotifier(Notifier):
    def __init__(self, webhook_url):
        self.webhook = webhook_url
    def send(self, text):
        requests.post(self.webhook, json={"content": text})
```

Send to several at once with `MultiNotifier([TelegramNotifier(), DiscordNotifier(url)])`.

## Test without messaging your phone

Temporarily use the console notifier — in a quick script or the Python REPL:

```python
from alerter import ConsoleNotifier, Watchlist, run_monitor_forever
wl = Watchlist("test", "binance", "USDT", ["BTC", "ETH", "SOL"])
run_monitor_forever([wl], ConsoleNotifier(), digest_hour_utc=0,
                    state_path="/tmp/test_state.json", once=True)
```

Alerts print to your terminal instead of Telegram.

## Running it 24/7

It's designed to run continuously (e.g. on a small always-on VM) under a
process manager like `systemd`, so it restarts on crashes and reboots. State
(who's oversold, who recovered today) is saved to `.rsi_monitor_state.json` so
restarts don't lose memory or re-send alerts.

> Note: Binance and Bybit block US IP addresses, so the host must be in a
> non-US region. If you can't use one, switch the `exchange` field in
> `watchlists.py` to one that allows your location (e.g. `gate`, `kucoin`).
