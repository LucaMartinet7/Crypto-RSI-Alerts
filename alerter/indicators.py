"""
Math building blocks ("technical indicators").

Each function takes a ``pandas`` Series (think: a column of numbers, usually
closing prices or volumes) plus a ``length`` (how many bars to look back) and
returns a new Series with the indicator's value at every bar.

The monitor only uses ``rsi`` today; ``sma`` and ``ema`` are kept as handy
building blocks if you want to add more conditions later.
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


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD = Moving Average Convergence Divergence, a momentum indicator.

    It compares a fast EMA to a slow EMA of price and returns three Series:
      - ``macd_line``   = EMA(fast) − EMA(slow)   (fast vs slow momentum)
      - ``signal_line`` = EMA(macd_line, signal)  (a smoothed version of it)
      - ``histogram``   = macd_line − signal_line (the gap between them)

    The classic trade signal is a *crossover*: when ``macd_line`` rises above
    ``signal_line`` it's "bullish" (momentum turning up); when it falls below,
    "bearish". Matches TradingView's ``ta.macd()`` with the same 12/26/9 inputs.
    """
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram
