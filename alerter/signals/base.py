"""
The shared contract for "detectors" — the pluggable bits that decide what
counts as an alert.

A detector watches ONE indicator (RSI, MACD, ...) across many symbols. On every
scan the monitor hands it a symbol's recent closing prices; the detector keeps a
little per-symbol memory (e.g. which RSI zone the coin is in) and returns an
Alert only when that memory genuinely changes — so you're pinged on the *event*,
not on every scan.

To add a new signal (Bollinger bands, a moving-average cross, ...):
    1. subclass Detector in its own file under this package,
    2. implement update() + the two state methods,
    3. add it to the detector list in run_monitor_forever() (monitor.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class Alert:
    """One thing worth telling the user about a single symbol. The monitor wraps
    these with the symbol name / exchange when it sends them."""
    emoji: str    # e.g. "🔻"
    title: str    # e.g. "crossed UNDER RSI 30 (oversold)"
    detail: str   # e.g. "RSI14 = `25.31`"


@dataclass
class DigestSection:
    """One block in the once-a-day summary: a heading and the symbol keys
    (like "binance:BTC/USDT") listed under it."""
    heading: str
    keys: list[str]


class Detector(ABC):
    """Base class for an indicator-based alert detector."""

    name: str = "detector"
    # False: update() gets the closing prices (a Series). True: it gets the full
    # candle table (DataFrame with ts, open, high, low, close, volume).
    needs_ohlcv: bool = False

    @property
    @abstractmethod
    def min_candles(self) -> int:
        """How many candles of history this detector needs to be accurate."""

    @abstractmethod
    def update(self, key: str, close: pd.Series | pd.DataFrame) -> list[Alert]:
        """Update one symbol's state from its closing-price series and return any
        alerts caused by a state change (an empty list when nothing changed)."""

    # --- persistence: all detectors share one JSON state file ---
    @abstractmethod
    def state_dict(self) -> dict:
        """This detector's state as JSON-friendly data (merged into the file)."""

    @abstractmethod
    def load_state(self, raw: dict) -> None:
        """Restore state from the loaded file (each detector reads its own keys)."""

    # --- optional daily-digest contribution (default: contributes nothing) ---
    def digest_sections(self) -> list[DigestSection]:
        """Blocks to include in the daily digest."""
        return []

    def reset_digest(self) -> None:  # noqa: B027 — optional hook, no-op by default
        """Clear any 'since last digest' accumulators, called after each digest."""

    # --- optional housekeeping ---
    def prune(self, live_keys: set[str]) -> None:  # noqa: B027 — optional hook
        """Forget any symbols no longer being watched (e.g. removed from a
        watchlist), so state doesn't grow forever. ``live_keys`` is the set of
        keys still in the config. Default: nothing to prune."""

