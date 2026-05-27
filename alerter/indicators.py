"""
Technical indicator primitives.

Add new indicators here (MACD, Bollinger, ATR, etc.) and import them
from your Strategy classes in strategies.py.
"""

from __future__ import annotations

import pandas as pd


def rsi(series: pd.Series, length: int) -> pd.Series:
    """Wilder's RSI — matches TradingView's ta.rsi()."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def sma(series: pd.Series, length: int) -> pd.Series:
    """Simple moving average — matches TradingView's ta.sma()."""
    return series.rolling(length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential moving average — matches TradingView's ta.ema()."""
    return series.ewm(span=length, adjust=False).mean()
