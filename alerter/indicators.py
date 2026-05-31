"""
Math building blocks ("technical indicators") used by the strategies.

Each function takes a ``pandas`` Series (think: a column of numbers, usually
closing prices or volumes) plus a ``length`` (how many bars to look back) and
returns a new Series with the indicator's value at every bar.

Add new indicators here (MACD, Bollinger, ATR, ...) and import them from your
Strategy classes in strategies.py.
"""

from __future__ import annotations

import pandas as pd


def rsi(series: pd.Series, length: int) -> pd.Series:
    """RSI = Relative Strength Index, a 0–100 "momentum" gauge.

    Roughly: it compares recent gains to recent losses. Low values (under ~30)
    mean the price has fallen a lot recently → "oversold". High values (over
    ~70) mean it has risen a lot → "overbought". This is Wilder's original
    formula and matches TradingView's ``ta.rsi()``.
    """
    delta = series.diff()                 # change from one bar to the next
    gain = delta.clip(lower=0.0)          # keep only the up moves
    loss = -delta.clip(upper=0.0)         # keep only the down moves (as positives)
    # Wilder's smoothing (an exponential average) of the gains and losses:
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss              # relative strength
    return 100 - (100 / (1 + rs))


def sma(series: pd.Series, length: int) -> pd.Series:
    """SMA = Simple Moving Average: the plain average of the last ``length``
    bars. Used here to define "normal" volume. Matches TradingView ``ta.sma()``."""
    return series.rolling(length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    """EMA = Exponential Moving Average: like an SMA but weights recent bars
    more heavily, so it reacts faster. Matches TradingView ``ta.ema()``."""
    return series.ewm(span=length, adjust=False).mean()
