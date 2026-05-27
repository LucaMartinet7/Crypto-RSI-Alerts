"""
A Watchlist is the unit of configuration: a list of symbols on a
specific exchange + timeframe, evaluated against a single strategy.

You can have as many Watchlists as you want, each with its own
exchange, timeframe, and strategy.
"""

from __future__ import annotations

from dataclasses import dataclass

from .strategies import Strategy


@dataclass
class Watchlist:
    name: str            # human-readable, shown in alerts and logs
    exchange: str        # ccxt id: "binance", "bybit", "kucoin", "okx", "mexc", ...
    quote: str           # "USDT", "USDC", "USD", "BTC", ...
    timeframe: str       # "15m", "1h", "4h", "1d", ...
    strategy: Strategy
    symbols: list[str]   # base assets, e.g. ["BTC", "ETH", "SOL"]
