"""
Public API for the alerter package.

Import what you need from here in your config and entry point:

    from alerter import Watchlist, TelegramNotifier, run_monitor_forever
"""

from .exchanges import get_exchange
from .indicators import rsi, sma, ema
from .monitor import RsiBandMonitor, run_monitor_forever
from .notifier import (
    ConsoleNotifier,
    MultiNotifier,
    Notifier,
    TelegramNotifier,
)
from .watchlist import Watchlist

__all__ = [
    # indicators
    "rsi", "sma", "ema",
    # exchanges
    "get_exchange",
    # notifiers
    "Notifier", "TelegramNotifier", "ConsoleNotifier", "MultiNotifier",
    # core
    "Watchlist",
    # rsi band monitor
    "RsiBandMonitor", "run_monitor_forever",
]
