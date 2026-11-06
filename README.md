# Crypto RSI Alerts

Telegram alerts for crypto **RSI** levels, **MACD** crossovers and a **BTC
buy-the-dip** setup. It watches every coin held on a **Revolut X** account (or a
fixed list you write) and pings you the moment a signal fires — plus a
once-a-day summary.

## What you get

**RSI** — each coin sits in one of three zones (**oversold** under 30,
**neutral**, or **overbought** over 70) and you get pinged whenever one moves:

- 🔻 RSI drops **under 30** (oversold)
- 🟢 RSI climbs **back over 30** (recovered)
- 📈 RSI rises **over 70** (overbought)
- 🔵 RSI drops **back under 70** (cooled off)

**MACD** — the classic crossover signal, independent of RSI:

- 🟩 **bullish cross** (MACD line crosses above its signal line)
- 🟥 **bearish cross** (MACD line crosses below its signal line)

**BTC buy-the-dip** 🟢 — a port of a TradingView swing-trading script. Fires
(at most once per daily candle, judged on the last *closed* day) only when all
five hold: weekly close > 20-week EMA > 50-week SMA · Stoch RSI (14,14,3,3) K
crosses above D below 20 · MACD histogram rising two bars · volume above its
20-day average · close within one ATR(14) of the 20-day low. It is very strict:
on BTC daily history from late 2018 to 2026 all five never lined up at once, so expect
it to stay silent for long stretches. It's a setup notice, not advice.

Alerts for coins you hold end with **"You hold 12.4 SOL"**.

**Daily digest** 🗓️ (08:00 UTC by default) — four RSI lists: currently oversold,
recovered since last digest, currently overbought, and cooled off since last
digest.

A note on candles: **RSI** and **MACD** are read from the **live,
in-progress candle**, so on the `1d` timeframe they move throughout the day and
alerts can fire any time, not just at the daily close. The trade-off is that a
value sitting right on its trigger can wobble across the line and send a few
alerts (per-symbol state means we only alert on a genuine flip, but some
back-and-forth near the edge is possible).

## Where coins and prices come from

- **Revolut X mode** (when `REVX_API_KEY` is set): every scan reads the
  account's balances (read-only API key) and watches every coin held — fiat,
  stablecoins and zero balances are skipped. Each coin is priced on the first
  source that lists it: **Revolut X** (USD pairs, so prices match what you trade
  at), then **Binance**, then **Bybit**. If Revolut X can't be reached, the last
  known list is kept.
- **Fixed-list mode** (no key): the coins in `watchlists.py`.

### Revolut X setup (once)

1. Create a signing key pair (keep `private.pem` secret, on the server only):
   ```bash
   openssl genpkey -algorithm ed25519 -out private.pem
   openssl pkey -in private.pem -pubout -out public.pem
   ```
2. In the Revolut X web app → Profile → **API keys**, paste `public.pem`. Give
   it **read access only** (no spot orders, no MCP/CLI), whitelist the server's
   IP, and pick the longest expiry. Note the expiry date.
3. Put the key in `.env`: `REVX_API_KEY=...` and
   `REVX_PRIVATE_KEY_FILE=/path/to/private.pem`.

When the key expires, create a new one with the same `public.pem` and update
`REVX_API_KEY`.

## File layout

```
Crypto-RSI-Alerts/
├── alerter/                  ← the engine (don't usually need to touch)
│   ├── __init__.py           what the package exposes
│   ├── indicators.py         rsi, sma, ema, macd, stoch_rsi, atr — the math
│   ├── notifier.py           Telegram / Console / Multi — where alerts go
│   ├── exchanges.py          builds + caches exchange connections
│   ├── revx.py               Revolut X API client (signed, read-only)
│   ├── holdings.py           held coins → watchlists, routed to a price source
│   ├── watchlist.py          the Watchlist dataclass
│   ├── config.py             MonitorConfig — all settings, read from env
│   ├── signals/              the pluggable "what counts as an alert?" logic
│   │   ├── base.py           Detector contract + Alert / DigestSection
│   │   ├── rsi.py            RsiZoneDetector (the 30 / 70 zone alerts)
│   │   ├── macd.py           MacdCrossDetector (bullish / bearish crossovers)
│   │   └── dip.py            BuyTheDipDetector (BTC 5-condition swing setup)
│   ├── state.py              JsonStateStore — atomic save/load of state
│   ├── lockfile.py           single-instance lock (no double-running)
│   └── monitor.py            orchestrator: fetch → run detectors → send → digest
├── tests/                    pytest suite (indicators, detectors, monitor, ...)
├── watchlists.py             ← fixed coin list (used when there's no Revolut X key)
├── .env                      ← your settings + credentials (not committed)
├── .env.example              ← template
├── requirements.txt          pinned runtime deps
├── requirements-dev.txt      + pytest & ruff for development
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
| `RSI_THRESHOLD` | `30` | oversold line (alert when RSI drops under) |
| `RSI_HIGH_THRESHOLD` | `70` | overbought line (alert when RSI rises over) |
| `MACD_FAST` / `MACD_SLOW` / `MACD_SIGNAL` | `12` / `26` / `9` | MACD crossover settings |
| `MONITOR_TIMEFRAME` | `1d` | candle size the indicators are computed on |
| `DIGEST_HOUR_UTC` | `8` | hour (UTC) the daily summary is sent |
| `MONITOR_INTERVAL` | `600` | seconds between scans |
| `LOG_LEVEL` | `INFO` | log verbosity |
| `REVX_API_KEY` | — | Revolut X API key; when set, watch the account's holdings |
| `REVX_PRIVATE_KEY_FILE` | — | path to the Ed25519 `private.pem` used to sign requests |

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

### Add a new kind of signal (e.g. Bollinger, MA cross)
Each indicator lives in its own detector under `alerter/signals/`. Subclass
`Detector`, return an `Alert` from `update()` when a symbol's state changes, then
add it to the detector list in `run_monitor_forever()` (`monitor.py`):

```python
from .base import Alert, Detector

class MyDetector(Detector):
    name = "mything"

    @property
    def min_candles(self): return 50

    def update(self, key, close):
        # ... compute something from the close-price series ...
        # (set needs_ohlcv = True on the class to get the full candle table)
        if just_crossed:
            return [Alert("🔔", "my signal fired", "detail = `...`")]
        return []

    def state_dict(self):       return {"mykey": self.state}
    def load_state(self, raw):  self.state = dict(raw.get("mykey", {}))
```

The monitor handles fetching, sending, persistence and the loop — you only write
the detection logic.

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
from alerter import ConsoleNotifier, MonitorConfig, Watchlist, run_monitor_forever
cfg = MonitorConfig(digest_hour_utc=0, state_path="/tmp/test_state.json")
wl = Watchlist("test", "binance", "USDT", ["BTC", "ETH", "SOL"])
run_monitor_forever([wl], ConsoleNotifier(), cfg, once=True)
```

Alerts print to your terminal instead of Telegram.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .     # lint
pytest           # run the test suite
```

CI runs both on every push; the deploy only happens if they pass.

## Running it 24/7

It's designed to run continuously (e.g. on a small always-on VM) under a
process manager like `systemd`, so it restarts on crashes and reboots.

- **State** (each coin's RSI zone / MACD side, who recovered today, the last
  digest date) is saved atomically to `.rsi_monitor_state.json`, so restarts
  don't lose memory or re-send alerts.
- A **single-instance lock** (`.rsi_monitor.lock`) stops two copies running at
  once — a second start refuses rather than double-sending alerts.

> Note: Binance and Bybit block US IP addresses, so the host must be in a
> non-US region. If you can't use one, switch the `exchange` field in
> `watchlists.py` to one that allows your location (e.g. `gate`, `kucoin`).
