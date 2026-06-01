"""
Public API for the alerter package.

Import what you need from here in your config and entry point:

    from alerter import Watchlist, TelegramNotifier, run_monitor_forever
"""

from .exchanges import get_exchange
from .indicators import rsi, sma, ema, macd
from .monitor import Monitor, run_monitor_forever
from .notifier import (
    ConsoleNotifier,
    MultiNotifier,
    Notifier,
    TelegramNotifier,
)
from .signals import Alert, Detector, DigestSection, MacdCrossDetector, RsiZoneDetector
from .state import JsonStateStore
from .watchlist import Watchlist

__all__ = [
    # indicators
    "rsi", "sma", "ema", "macd",
    # exchanges
    "get_exchange",
    # notifiers
    "Notifier", "TelegramNotifier", "ConsoleNotifier", "MultiNotifier",
    # core
    "Watchlist",
    # signal detectors
    "Detector", "Alert", "DigestSection", "RsiZoneDetector", "MacdCrossDetector",
    # persistence
    "JsonStateStore",
    # monitor
    "Monitor", "run_monitor_forever",
]
