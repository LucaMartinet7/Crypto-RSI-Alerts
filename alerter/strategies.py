"""
Strategies decide whether the most recent candle deserves an alert.

To add a new strategy:
    1. Subclass Strategy.
    2. Set self.min_candles (how much history you need).
    3. Set self.name (used in logs).
    4. Implement evaluate(df) — return Signal(...) on a hit, else None.
    5. Use it in watchlists.py.

The DataFrame given to evaluate() has columns:
    ts, open, high, low, close, volume
Always use df.iloc[-2] for the most recent CLOSED candle.
df.iloc[-1] is the in-progress candle (flickers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from .indicators import rsi, sma


@dataclass
class Signal:
    """A formatted alert ready to be sent."""
    title: str   # short headline, e.g. "🚨 RSI Oversold + Volume Spike"
    detail: str  # multi-line body of the alert


class Strategy(ABC):
    """Base class for all alert strategies."""

    name: str = "abstract"
    min_candles: int = 30

    @abstractmethod
    def evaluate(self, df: pd.DataFrame) -> Signal | None:
        ...


# =====================================================================
# Strategy: RSI oversold + volume spike  (your original Pine Script)
# =====================================================================
class RsiVolumeSpike(Strategy):
    """
    Fires when RSI(rsi_length) < rsi_threshold AND
                volume > SMA(volume, vol_length) * vol_multiplier.

    vol_multiplier = 1.0 → matches the original Pine Script (any above-average bar).
    vol_multiplier = 1.5 → only fires on a real 1.5x spike. Less noise.
    """

    def __init__(
        self,
        rsi_length: int = 14,
        rsi_threshold: float = 30,
        vol_length: int = 20,
        vol_multiplier: float = 1.0,
    ):
        self.rsi_length     = rsi_length
        self.rsi_threshold  = rsi_threshold
        self.vol_length     = vol_length
        self.vol_multiplier = vol_multiplier
        self.min_candles    = max(rsi_length, vol_length) + 5
        self.name = (
            f"RSI<{rsi_threshold} & Vol>{vol_multiplier:g}xSMA{vol_length}"
        )

    def evaluate(self, df: pd.DataFrame) -> Signal | None:
        r   = rsi(df["close"], self.rsi_length).iloc[-2]
        v   = df["volume"].iloc[-2]
        vma = sma(df["volume"], self.vol_length).iloc[-2]

        if pd.isna(r) or pd.isna(vma):
            return None

        threshold = vma * self.vol_multiplier
        if r < self.rsi_threshold and v > threshold:
            return Signal(
                title="🚨 RSI Oversold + Volume Spike",
                detail=(
                    f"RSI{self.rsi_length}  = `{r:.2f}`  (< {self.rsi_threshold})\n"
                    f"Volume = `{v:,.2f}`  >  "
                    f"SMA{self.vol_length}×{self.vol_multiplier:g} = `{threshold:,.2f}`"
                ),
            )
        return None


# =====================================================================
# Strategy: RSI overbought  (mirror image — for tops)
# =====================================================================
class RsiOverbought(Strategy):
    """Fires when RSI(rsi_length) > rsi_threshold."""

    def __init__(self, rsi_length: int = 14, rsi_threshold: float = 70):
        self.rsi_length    = rsi_length
        self.rsi_threshold = rsi_threshold
        self.min_candles   = rsi_length + 5
        self.name = f"RSI>{rsi_threshold}"

    def evaluate(self, df: pd.DataFrame) -> Signal | None:
        r = rsi(df["close"], self.rsi_length).iloc[-2]
        if pd.isna(r):
            return None
        if r > self.rsi_threshold:
            return Signal(
                title="📈 RSI Overbought",
                detail=f"RSI{self.rsi_length} = `{r:.2f}`  (> {self.rsi_threshold})",
            )
        return None


# =====================================================================
# Strategy: Price breakout above N-period high  (example of "add your own")
# =====================================================================
class PriceBreakout(Strategy):
    """Fires when the last close breaks above the highest high of the prior N candles."""

    def __init__(self, lookback: int = 20):
        self.lookback    = lookback
        self.min_candles = lookback + 5
        self.name = f"Breakout>{lookback}-bar high"

    def evaluate(self, df: pd.DataFrame) -> Signal | None:
        close       = df["close"].iloc[-2]
        prior_high  = df["high"].iloc[-2 - self.lookback : -2].max()
        if pd.isna(prior_high):
            return None
        if close > prior_high:
            return Signal(
                title="🚀 Price Breakout",
                detail=(
                    f"Close = `{close:,.4f}`  >  "
                    f"{self.lookback}-bar high = `{prior_high:,.4f}`"
                ),
            )
        return None
