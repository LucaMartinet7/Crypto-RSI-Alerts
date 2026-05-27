"""
Scanner — orchestrates the loop:
    for each watchlist
        for each symbol
            fetch candles, evaluate strategy, dispatch alert if hit

Exchange instances are cached so we don't reload markets every cycle.
Alerts are de-duped per (watchlist, symbol, candle_timestamp).
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

# Reuse exchange instances across scans (markets are heavy to reload).
_exchanges: dict[str, ccxt.Exchange] = {}

# Dedupe: (watchlist_name, symbol) -> ts of the last candle we alerted on.
_already_fired: dict[tuple[str, str], int] = {}


def _get_exchange(exchange_id: str) -> ccxt.Exchange:
    if exchange_id not in _exchanges:
        log.info("Loading markets for %s ...", exchange_id)
        cls = getattr(ccxt, exchange_id)
        ex = cls({"enableRateLimit": True})
        ex.load_markets()
        _exchanges[exchange_id] = ex
    return _exchanges[exchange_id]


def scan_watchlist(wl: Watchlist, notifier: Notifier) -> int:
    """Run one scan of a single watchlist. Returns count of alerts fired."""
    exchange = _get_exchange(wl.exchange)
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
