# RSI + Volume alerter (modular edition)

Sends Telegram alerts when crypto symbols meet your custom strategy
conditions across one or more exchanges and timeframes.

## File layout

```
rsi-alerter/
├── alerter/                  ← the engine (don't usually need to touch)
│   ├── __init__.py
│   ├── indicators.py         rsi, sma, ema — add new ones here
│   ├── strategies.py         alert logic — add new strategies here
│   ├── notifier.py           Telegram / Console / Multi — add channels here
│   ├── watchlist.py          Watchlist dataclass
│   └── scanner.py            scan loop
├── watchlists.py             ← what to monitor (edit this)
├── .env                      ← your credentials (create from .env.example)
├── .env.example              ← template
├── requirements.txt
├── run.py                    ← python3 run.py
└── README.md
```

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# now edit .env with your real TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

python3 run.py
```

That's it. No `export` commands needed — `.env` is read automatically every
time you run the script.

## How to add things

### Add symbols to an existing watchlist
Open `watchlists.py`, find the watchlist, add the symbol to the
`symbols=[...]` list. Done.

### Add a new watchlist on a different exchange or timeframe
Append a new `Watchlist(...)` to the `WATCHLISTS` list in `watchlists.py`:

```python
Watchlist(
    name="my-new-list",
    exchange="kucoin",
    quote="USDT",
    timeframe="4h",
    strategy=strat_oversold,
    symbols=["BTC", "ETH", "SOL"],
),
```

### Add a new alert strategy
Open `alerter/strategies.py`, subclass `Strategy`:

```python
class MacdCrossUp(Strategy):
    def __init__(self):
        self.min_candles = 50
        self.name = "MACD bullish cross"

    def evaluate(self, df):
        # ... compute MACD on df["close"] ...
        if signal_just_crossed_above_macd:
            return Signal(title="MACD Cross Up", detail=f"...")
        return None
```

Then use it in `watchlists.py`:
```python
strategy=MacdCrossUp(),
```

### Add a new notification channel
Open `alerter/notifier.py`, subclass `Notifier`:

```python
class DiscordNotifier(Notifier):
    def __init__(self, webhook_url):
        self.webhook = webhook_url
    def send(self, text):
        requests.post(self.webhook, json={"content": text})
```

Send to multiple channels at once:
```python
notifier = MultiNotifier([TelegramNotifier(), DiscordNotifier(url)])
```

### Tweak how often it scans
Edit `SCAN_INTERVAL` in `.env`. No restart-of-anything-else needed.

## Test without spamming your phone

In `run.py`, swap:
```python
from alerter import ConsoleNotifier
notifier = ConsoleNotifier()
```
Alerts print to your terminal instead of Telegram.
