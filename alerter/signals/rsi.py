"""
RSI zone detector.

Every symbol sits in one of three zones based on its live RSI:
    oversold   — RSI below the low threshold  (default < 30)
    neutral    — in between
    overbought — RSI above the high threshold (default > 70)

An alert fires whenever a symbol moves from one zone to another:
    🔻 into oversold      🟢 back out of oversold (recovered)
    📈 into overbought    🔵 back out of overbought (cooled off)

RSI is taken from the LIVE, in-progress candle (iloc[-1]) so it moves with price
all day and alerts can fire intraday, not only at the daily close.
"""

from __future__ import annotations

import pandas as pd

from ..indicators import rsi
from .base import Alert, Detector, DigestSection

OVERSOLD = "oversold"
NEUTRAL = "neutral"
OVERBOUGHT = "overbought"


class RsiZoneDetector(Detector):
    name = "rsi"

    def __init__(self, length: int = 14,
                 oversold: float = 30.0, overbought: float = 70.0):
        self.length = length
        self.oversold = oversold
        self.overbought = overbought
        # per-symbol memory:
        self.zone: dict[str, str] = {}          # key -> current zone
        self.recovered_today: set[str] = set()  # left oversold since last digest
        self.cooled_today: set[str] = set()     # left overbought since last digest

    @property
    def min_candles(self) -> int:
        return self.length + 2

    def _zone(self, r: float) -> str:
        if r < self.oversold:
            return OVERSOLD
        if r > self.overbought:
            return OVERBOUGHT
        return NEUTRAL

    def update(self, key: str, close: pd.Series) -> list[Alert]:
        r = rsi(close, self.length).iloc[-1]   # live candle
        if pd.isna(r):
            return []
        r = float(r)
        new = self._zone(r)
        prev = self.zone.get(key)              # None == never seen before

        if prev is None:
            self.zone[key] = new               # first sighting: record silently
            return []
        if new == prev:
            return []                          # same zone — nothing to announce

        lo, hi, val = self.oversold, self.overbought, f"RSI{self.length} = `{r:.2f}`"
        alert: Alert
        if new == OVERSOLD:
            alert = Alert("🔻", f"crossed UNDER RSI {lo:g} (oversold)", val)
        elif new == OVERBOUGHT:
            alert = Alert("📈", f"crossed OVER RSI {hi:g} (overbought)", val)
        elif prev == OVERSOLD:                 # oversold -> neutral
            alert = Alert("🟢", f"recovered back over RSI {lo:g}", val)
            self.recovered_today.add(key)
        else:                                  # overbought -> neutral
            alert = Alert("🔵", f"cooled back under RSI {hi:g}", val)
            self.cooled_today.add(key)

        self.zone[key] = new
        return [alert]

    # --- persistence (same JSON keys the app has always used) ---
    def state_dict(self) -> dict:
        return {
            "zone": self.zone,
            "recovered_today": sorted(self.recovered_today),
            "cooled_today": sorted(self.cooled_today),
        }

    def load_state(self, raw: dict) -> None:
        self.zone = dict(raw.get("zone", {}))
        self.recovered_today = set(raw.get("recovered_today", []))
        self.cooled_today = set(raw.get("cooled_today", []))

    # --- daily digest ---
    def digest_sections(self) -> list[DigestSection]:
        lo, hi = self.oversold, self.overbought
        oversold = sorted(k for k, z in self.zone.items() if z == OVERSOLD)
        overbought = sorted(k for k, z in self.zone.items() if z == OVERBOUGHT)
        return [
            DigestSection(f"🔻 *Currently oversold (under {lo:g}):*", oversold),
            DigestSection(f"🟢 *Recovered (back over {lo:g}) since last digest:*",
                          sorted(self.recovered_today)),
            DigestSection(f"📈 *Currently overbought (over {hi:g}):*", overbought),
            DigestSection(f"🔵 *Cooled off (back under {hi:g}) since last digest:*",
                          sorted(self.cooled_today)),
        ]

    def reset_digest(self) -> None:
        self.recovered_today.clear()
        self.cooled_today.clear()
