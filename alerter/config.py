"""
All of the monitor's tunable settings in one place.

Keeping them in a dataclass (instead of a long list of function arguments) makes
the monitor easy to construct, easy to extend with new settings, and trivial to
build in tests. ``MonitorConfig.from_env()`` is the single spot that reads
environment variables, so run.py stays tiny and nothing else touches os.environ.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MonitorConfig:
    # RSI
    rsi_length: int = 14
    oversold_threshold: float = 30.0
    overbought_threshold: float = 70.0
    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    # scheduling / data
    timeframe: str = "1d"
    digest_hour_utc: int = 8
    interval_seconds: int = 600
    # files
    state_path: str = ".rsi_monitor_state.json"
    lock_path: str = ".rsi_monitor.lock"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> MonitorConfig:
        """Build a config from environment variables, falling back to the
        defaults above. Pass ``env`` explicitly in tests."""
        e = env if env is not None else os.environ
        return cls(
            rsi_length=int(e.get("RSI_LENGTH", "14")),
            oversold_threshold=float(e.get("RSI_THRESHOLD", "30")),
            overbought_threshold=float(e.get("RSI_HIGH_THRESHOLD", "70")),
            macd_fast=int(e.get("MACD_FAST", "12")),
            macd_slow=int(e.get("MACD_SLOW", "26")),
            macd_signal=int(e.get("MACD_SIGNAL", "9")),
            timeframe=e.get("MONITOR_TIMEFRAME", "1d"),
            digest_hour_utc=int(e.get("DIGEST_HOUR_UTC", "8")),
            interval_seconds=int(e.get("MONITOR_INTERVAL", "600")),
            state_path=e.get("MONITOR_STATE_FILE", ".rsi_monitor_state.json"),
            lock_path=e.get("MONITOR_LOCK_FILE", ".rsi_monitor.lock"),
        )
