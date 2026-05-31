"""
Exchange helper — builds and caches connections to crypto exchanges.

An "exchange" object (from the ccxt library) is how we talk to Binance, Bybit,
etc. to download price data. Loading an exchange's list of tradable markets is
slow, so we create each one once and reuse it for the life of the process.
"""

from __future__ import annotations

import logging

import ccxt

log = logging.getLogger("alerter.exchanges")

# exchange id ("binance") -> a ready-to-use, markets-loaded ccxt exchange object.
_exchanges: dict[str, ccxt.Exchange] = {}


def get_exchange(exchange_id: str) -> ccxt.Exchange:
    """Return a ready-to-use exchange object for e.g. "binance", building and
    caching it on first use."""
    if exchange_id not in _exchanges:
        log.info("Loading markets for %s ...", exchange_id)
        cls = getattr(ccxt, exchange_id)               # e.g. ccxt.binance
        ex = cls({"enableRateLimit": True})            # auto-throttle requests
        ex.load_markets()                              # download tradable pairs
        _exchanges[exchange_id] = ex
    return _exchanges[exchange_id]
