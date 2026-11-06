"""
BTC "buy-the-dip" detector — a port of the TradingView "BTC Buy-the-Dip Alert"
script (daily chart, 1–4 week swing horizon). It alerts when ALL five hold on
the last CLOSED daily candle:

    1. weekly trend bullish: weekly close > 20-week EMA > 50-week SMA
    2. Stoch RSI (14,14,3,3) K crosses above D, with min(K, D) under 20
    3. MACD (12,26,9) histogram rising two bars in a row
    4. volume above its 20-day average
    5. close within one ATR(14) of the 20-day low (a rough support proxy)

Like the TradingView alert set to "Once Per Bar Close", it judges the last
finished daily candle (the live one is dropped) and fires at most once per
candle. As in the script, the weekly values include the still-forming week.
It is a buy-*setup* notification, not advice and not an automatic order.
"""

from __future__ import annotations

import pandas as pd

from ..indicators import atr, ema, macd, sma, stoch_rsi
from .base import Alert, Detector

_HISTORY_DAYS = 500   # 50-week SMA needs ~350 days; the rest warms up the EMAs


def _crossover(a: pd.Series, b: pd.Series) -> bool:
    """Pine's ta.crossover: a is above b now, and was at/below it one bar ago."""
    return bool(a.iloc[-1] > b.iloc[-1] and a.iloc[-2] <= b.iloc[-2])


def dip_conditions(c: pd.DataFrame) -> dict[str, bool]:
    """Evaluate the five rules on the LAST row of daily candles `c`
    (columns ts[ms], open, high, low, close, volume). NaN => False."""
    close, high, low, volume = c["close"], c["high"], c["low"], c["volume"]

    # TradingView weeks run Monday-Sunday UTC; the last week may be partial.
    day = pd.to_datetime(c["ts"], unit="ms", utc=True).dt.tz_localize(None)
    weekly = close.groupby(day.dt.to_period("W-SUN").values).last()
    w_ema20, w_sma50 = ema(weekly, 20).iloc[-1], sma(weekly, 50).iloc[-1]

    k, d = stoch_rsi(close, 14, 14, 3, 3)
    _, _, hist = macd(close, 12, 26, 9)
    atr14 = atr(high, low, close, 14)

    return {
        "weekly trend": bool(weekly.iloc[-1] > w_ema20 > w_sma50),
        "stoch RSI cross": _crossover(k, d) and bool(min(k.iloc[-1], d.iloc[-1]) < 20),
        "MACD improving": bool(hist.iloc[-1] > hist.iloc[-2] > hist.iloc[-3]),
        "volume": bool(volume.iloc[-1] > sma(volume, 20).iloc[-1]),
        "near support": bool(close.iloc[-1]
                             <= low.rolling(20).min().iloc[-1] + atr14.iloc[-1]),
    }


class BuyTheDipDetector(Detector):
    name = "btc-dip"
    needs_ohlcv = True

    def __init__(self, bases: frozenset[str] = frozenset({"BTC"})):
        self.bases = bases
        self.last_signal: dict[str, int] = {}   # key -> start (ms) of candle alerted

    @property
    def min_candles(self) -> int:
        return _HISTORY_DAYS

    def update(self, key: str, candles: pd.DataFrame) -> list[Alert]:
        base = key.split(":", 1)[-1].split("/")[0]
        if base not in self.bases:
            return []
        closed = candles.iloc[:-1]                 # drop the live, unfinished candle
        if not all(dip_conditions(closed).values()):
            return []
        bar = int(closed["ts"].iloc[-1])
        if self.last_signal.get(key) == bar:
            return []                              # already alerted for this candle
        self.last_signal = {**self.last_signal, key: bar}
        day = pd.to_datetime(bar, unit="ms", utc=True)
        return [Alert(
            "🟢", "BUY-THE-DIP setup (all 5 conditions)",
            f"Daily close {day:%Y-%m-%d} at `{closed['close'].iloc[-1]:,.2f}`: weekly "
            "uptrend, Stoch RSI cross <20, MACD improving, volume up, near 20-day low.\n"
            "_Setup only — check the chart and set a stop before buying._",
        )]

    def state_dict(self) -> dict:
        return {"dip_last_signal": self.last_signal}

    def load_state(self, raw: dict) -> None:
        self.last_signal = dict(raw.get("dip_last_signal", {}))

    def prune(self, live_keys: set[str]) -> None:
        self.last_signal = {k: v for k, v in self.last_signal.items() if k in live_keys}
