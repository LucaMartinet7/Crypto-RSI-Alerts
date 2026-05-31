"""
Public API for the alerter package.

Import what you need from here in your config and entry point:

    from alerter import Watchlist, RsiVolumeSpike, TelegramNotifier, run_forever
"""

from .indicators import rsi, sma, ema
from .monitor import RsiBandMonitor, run_monitor_forever
from .notifier import (
    ConsoleNotifier,
    MultiNotifier,
    Notifier,
    TelegramNotifier,
)
from .scanner import run_forever, scan_watchlist
from .strategies import (
    PriceBreakout,
    RsiOverbought,
    RsiVolumeSpike,
    Signal,
    Strategy,
)
from .watchlist import Watchlist

__all__ = [
    # indicators
    "rsi", "sma", "ema",
    # strategies
    "Strategy", "Signal",
    "RsiVolumeSpike", "RsiOverbought", "PriceBreakout",
    # notifiers
    "Notifier", "TelegramNotifier", "ConsoleNotifier", "MultiNotifier",
    # core
    "Watchlist", "scan_watchlist", "run_forever",
    # rsi band monitor
    "RsiBandMonitor", "run_monitor_forever",
]
