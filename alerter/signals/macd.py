"""
MACD crossover detector.

Tracks which side of its signal line each symbol's MACD line is on:
    bull — MACD line at or above the signal line
    bear — MACD line below the signal line

An alert fires when that flips (the classic MACD crossover):
    🟩 bullish cross (MACD crosses above signal)
    🟥 bearish cross (MACD crosses below signal)

Read from the LIVE, in-progress candle (iloc[-1]) so crosses are caught intraday
rather than only at the daily close. The trade-off is possible whipsaw when the
two lines hover right on top of each other.
"""

from __future__ import annotations

import pandas as pd

from ..indicators import macd
from .base import Alert, Detector

BULL = "bull"
BEAR = "bear"


class MacdCrossDetector(Detector):
    name = "macd"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.side: dict[str, str] = {}   # key -> "bull" / "bear"

    @property
    def min_candles(self) -> int:
        return self.slow + self.signal + 2

    def update(self, key: str, close: pd.Series) -> list[Alert]:
        macd_line, signal_line, _ = macd(close, self.fast, self.slow, self.signal)
        m, s = macd_line.iloc[-1], signal_line.iloc[-1]   # live candle
        if pd.isna(m) or pd.isna(s):
            return []

        new = BULL if m >= s else BEAR
        prev = self.side.get(key)

        if prev is None:
            self.side[key] = new          # first sighting: record silently
            return []
        if new == prev:
            return []                     # no crossover since last scan

        self.side[key] = new
        params = f"({self.fast}/{self.slow}/{self.signal})"
        if new == BULL:
            return [Alert("🟩", "MACD bullish cross",
                          f"MACD `{m:.4g}` above signal `{s:.4g}` {params}")]
        return [Alert("🟥", "MACD bearish cross",
                      f"MACD `{m:.4g}` below signal `{s:.4g}` {params}")]

    # --- persistence (same JSON key the app has always used) ---
    def state_dict(self) -> dict:
        return {"macd_side": self.side}

    def load_state(self, raw: dict) -> None:
        self.side = dict(raw.get("macd_side", {}))

    def prune(self, live_keys: set[str]) -> None:
        self.side = {k: v for k, v in self.side.items() if k in live_keys}
