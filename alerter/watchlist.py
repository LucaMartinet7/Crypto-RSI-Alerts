"""
A Watchlist is the basic unit of configuration: a group of coins to watch on
one exchange, priced in one quote currency.

You can have as many Watchlists as you like (e.g. one per exchange). The RSI
monitor reads every Watchlist on each scan. The RSI settings themselves
(length, threshold, candle timeframe) are global and live in .env — see run.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Watchlist:
    name: str            # human-readable label, shown in alerts and logs
    exchange: str        # ccxt id: "binance", "bybit", "kucoin", "okx", "mexc", ...
    quote: str           # quote currency: "USDT", "USDC", "USD", "BTC", ...
    symbols: list[str]   # base assets to watch, e.g. ["BTC", "ETH", "SOL"]
