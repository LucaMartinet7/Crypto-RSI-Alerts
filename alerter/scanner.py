"""
Strategy scanner — the *original* alerter, kept for reference / alternative use.

What it does, in plain terms:
    for each watchlist (a group of coins on one exchange)
        for each coin
            download recent price "candles"
            ask the watchlist's Strategy "is this an alert?"
            if yes, send a message (and remember it so we don't repeat it)

A "candle" (OHLCV) is one row of price data for a time slice: Open, High,
Low, Close prices and the trading Volume. We look at the most recently
*closed* candle, because the current one is still changing.

Note: the live RSI band monitor in ``monitor.py`` is what actually runs in
production. This scanner is the simpler, stateless predecessor.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import ccxt
import pandas as pd

from .notifier import Notifier
from .watchlist import Watchlist

log = logging.getLogger("alerter.scanner")

# An "exchange" object (from the ccxt library) knows how to talk to Binance,
# Bybit, etc. Loading its list of tradable markets is slow, so we build each
# one once and reuse it. This cache is shared with monitor.py via get_exchange.
_exchanges: dict[str, ccxt.Exchange] = {}

# Remembers the last candle we already alerted on, so the same candle can't
# trigger two alerts. Keyed by (watchlist_name, symbol) -> candle timestamp.
_already_fired: dict[tuple[str, str], int] = {}


def get_exchange(exchange_id: str) -> ccxt.Exchange:
    """Return a ready-to-use exchange object for e.g. "binance", building and
    caching it on first use. Reused by both the scanner and the monitor."""
    if exchange_id not in _exchanges:
        log.info("Loading markets for %s ...", exchange_id)
        cls = getattr(ccxt, exchange_id)               # e.g. ccxt.binance
        ex = cls({"enableRateLimit": True})            # auto-throttle requests
        ex.load_markets()                              # download tradable pairs
        _exchanges[exchange_id] = ex
    return _exchanges[exchange_id]


def scan_watchlist(wl: Watchlist, notifier: Notifier) -> int:
    """Run one scan of a single watchlist. Returns count of alerts fired."""
    exchange = get_exchange(wl.exchange)
    markets  = exchange.markets
    hits = 0

    for base in wl.symbols:
        symbol = f"{base}/{wl.quote}"
        if symbol not in markets:
            log.debug("[%s] skip %s (not listed on %s)", wl.name, symbol, wl.exchange)
            continue

        try:
            limit = max(wl.strategy.min_candles + 5, 50)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=wl.timeframe, limit=limit)
            if len(ohlcv) < wl.strategy.min_candles + 1:
                continue

            df = pd.DataFrame(
                ohlcv,
                columns=["ts", "open", "high", "low", "close", "volume"],
            )

            signal = wl.strategy.evaluate(df)
            if signal is None:
                continue

            ts  = int(df["ts"].iloc[-2])
            key = (wl.name, symbol)
            if _already_fired.get(key) == ts:
                continue
            _already_fired[key] = ts

            when = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            msg = (
                f"{signal.title}\n"
                f"*{symbol}*  on  *{wl.exchange}*  ({wl.timeframe})\n"
                f"{signal.detail}\n"
                f"Candle close: {when:%Y-%m-%d %H:%M UTC}\n"
                f"_watchlist: {wl.name}_"
            )
            log.info("ALERT  [%s]  %s", wl.name, symbol)
            notifier.send(msg)
            hits += 1

        except ccxt.BaseError as e:
            log.warning("ccxt error [%s] %s: %s", wl.name, symbol, e)
        except Exception as e:
            log.exception("error [%s] %s: %s", wl.name, symbol, e)

        # Respect the exchange's rate limit.
        time.sleep(exchange.rateLimit / 1000)

    return hits


def run_forever(
    watchlists: list[Watchlist],
    notifier: Notifier,
    interval_seconds: int = 900,
    once: bool = False,
) -> None:
    """Main loop: scan all watchlists, sleep, repeat.

    Pass once=True to scan once and exit — used by GitHub Actions.
    """
    log.info("Starting alerter with %d watchlist(s):", len(watchlists))
    for wl in watchlists:
        log.info(
            "  [%s] %d symbols on %s/%s (%s)  →  %s",
            wl.name, len(wl.symbols), wl.exchange, wl.quote,
            wl.timeframe, wl.strategy.name,
        )

    while True:
        try:
            total = 0
            for wl in watchlists:
                total += scan_watchlist(wl, notifier)
            if once:
                log.info("Cycle complete — %d alert(s) total. Exiting.", total)
            else:
                log.info("Cycle complete — %d alert(s) total. Sleeping %ds.",
                         total, interval_seconds)
        except Exception as e:
            log.exception("scan cycle crashed: %s", e)

        if once:
            break
        time.sleep(interval_seconds)
