"""
Monitor — the orchestrator, and the heart of the app.

It loops forever. On each pass it:
    1. downloads recent candles for every coin in your watchlists,
    2. hands the closing prices to each *detector* (see alerter/signals/),
    3. sends a Telegram message for any alert a detector returns,
    4. once a day, sends a digest summarising the current state.

The monitor knows nothing about RSI or MACD — that logic lives in the detectors.
It only fetches data, runs whatever detectors it was given, sends messages, and
saves state (via a JsonStateStore). To add a new kind of signal you write a
detector; you don't touch this file.

State (every detector's per-symbol memory + the last digest date) is saved to a
JSON file so a restart doesn't lose it or re-send alerts. Designed to run as a
long-lived process (e.g. on a small VM), not as a one-shot job.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd

from .exchanges import get_exchange
from .notifier import Notifier
from .signals import Alert, Detector, MacdCrossDetector, RsiZoneDetector
from .state import JsonStateStore
from .watchlist import Watchlist

log = logging.getLogger("alerter.monitor")

# How many candles to pull. Wilder's RSI / MACD need a long warm-up to match
# TradingView closely, so we fetch generously.
_FETCH_LIMIT = 300


class Monitor:
    """Fetches prices for each watchlist symbol, runs a set of detectors over
    them, sends the resulting alerts, and emits a once-a-day digest."""

    def __init__(
        self,
        watchlists: list[Watchlist],
        notifier: Notifier,
        detectors: list[Detector],
        timeframe: str = "1d",
        digest_hour_utc: int = 8,
        state_path: str | Path = ".rsi_monitor_state.json",
    ):
        self.watchlists      = watchlists
        self.notifier        = notifier
        self.detectors       = detectors
        self.timeframe       = timeframe
        self.digest_hour_utc = digest_hour_utc
        self.store           = JsonStateStore(state_path)
        # Fetch enough history for the hungriest detector.
        self._min_candles    = max(d.min_candles for d in detectors)
        self.last_digest_date: date | None = None
        self._load_state()

    # ------------------------------------------------------------------ state
    def _load_state(self) -> None:
        """Load saved state on startup; each detector picks out its own keys."""
        raw = self.store.load()
        for d in self.detectors:
            d.load_state(raw)
        last = raw.get("last_digest_date")
        self.last_digest_date = date.fromisoformat(last) if last else None

    def _save_state(self) -> None:
        """Collect every detector's state (plus the digest date) and persist it."""
        data: dict = {
            "last_digest_date":
                self.last_digest_date.isoformat() if self.last_digest_date else None,
        }
        for d in self.detectors:
            data.update(d.state_dict())
        self.store.save(data)

    # ------------------------------------------------------------------ scan
    def scan_once(self) -> None:
        """One pass over every watchlist and symbol."""
        for wl in self.watchlists:
            exchange = self._exchange_for(wl)
            if exchange is None:
                continue
            for base in wl.symbols:
                self._scan_symbol(exchange, wl, base)
        self._save_state()

    def _exchange_for(self, wl: Watchlist) -> ccxt.Exchange | None:
        """The (cached) exchange for a watchlist, or None if it can't be loaded
        — e.g. geo-blocked — so one bad exchange just skips, never crashes."""
        try:
            return get_exchange(wl.exchange)
        except Exception as e:
            log.error("could not load exchange %s (%s) — skipping watchlist %r",
                      wl.exchange, e, wl.name)
            return None

    def _scan_symbol(self, exchange: ccxt.Exchange, wl: Watchlist, base: str) -> None:
        """Fetch one symbol's prices and run every detector over them."""
        symbol = f"{base}/{wl.quote}"
        if symbol not in (exchange.markets or {}):
            log.debug("skip %s (not listed on %s)", symbol, wl.exchange)
            return
        key = f"{wl.exchange}:{symbol}"
        try:
            close = self._fetch_close(exchange, symbol)
            if close is not None:
                self._run_detectors(key, symbol, wl, close)
        except ccxt.BaseError as e:
            log.warning("ccxt error %s: %s", symbol, e)
        except Exception as e:
            log.exception("error %s: %s", symbol, e)
        time.sleep(exchange.rateLimit / 1000)   # respect the exchange rate limit

    def _fetch_close(self, exchange: ccxt.Exchange, symbol: str) -> pd.Series | None:
        """Download recent candles and return just the closing-price column
        (None if there isn't enough history). One fetch feeds every detector."""
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=self.timeframe,
                                     limit=_FETCH_LIMIT)
        if len(ohlcv) < self._min_candles:
            return None
        return pd.DataFrame(
            ohlcv, columns=["ts", "open", "high", "low", "close", "volume"]
        )["close"]

    def _run_detectors(self, key: str, symbol: str, wl: Watchlist,
                       close: pd.Series) -> None:
        """Run each detector on one symbol and send whatever alerts they raise."""
        fired = False
        for d in self.detectors:
            for alert in d.update(key, close):
                self._send_alert(symbol, wl, alert)
                fired = True
        # Save right after an alert so a crash can't cause us to re-send it.
        if fired:
            self._save_state()

    def _send_alert(self, symbol: str, wl: Watchlist, a: Alert) -> None:
        """Wrap a detector's Alert with the symbol/exchange context and send it."""
        log.info("ALERT  %s  %s", symbol, a.title)
        self.notifier.send(
            f"{a.emoji} *{symbol}* {a.title}\n"
            f"on *{wl.exchange}* ({self.timeframe})\n"
            f"{a.detail}"
        )

    # --------------------------------------------------------------- digest
    def maybe_send_digest(self) -> None:
        """Send the daily digest once, at/after digest_hour_utc each day."""
        now = datetime.now(timezone.utc)
        today = now.date()
        already_sent_today = (
            self.last_digest_date is not None and self.last_digest_date >= today
        )
        if now.hour < self.digest_hour_utc or already_sent_today:
            return

        self._send_digest(today)
        self.last_digest_date = today
        for d in self.detectors:
            d.reset_digest()
        self._save_state()

    def _send_digest(self, today: date) -> None:
        """Build and send the once-a-day summary from each detector's sections."""
        def label(key: str) -> str:
            exch, sym = key.split(":", 1)        # "binance:BTC/USDT" -> "BTC/USDT (binance)"
            return f"{sym} ({exch})"

        def block(keys: list[str]) -> str:
            return "\n".join(f"• {label(k)}" for k in keys) if keys else "_none_"

        sections = [
            f"{sec.heading}\n{block(sec.keys)}"
            for d in self.detectors
            for sec in d.digest_sections()
        ]
        log.info("DIGEST sent (%d sections)", len(sections))
        self.notifier.send(
            f"🗓️ *Daily digest* — {today:%Y-%m-%d} {self.digest_hour_utc:02d}:00 UTC\n"
            f"_{self.timeframe} candles_\n\n"
            + "\n\n".join(sections)
        )

    # ------------------------------------------------------------------ loop
    def run(self, interval_seconds: int = 600, once: bool = False) -> None:
        """Scan, send the digest if due, sleep, repeat — until stopped.
        Pass once=True to do a single pass then return (used by tests)."""
        log.info(
            "Monitor: %d symbols across %d watchlist(s), %s candles. "
            "Detectors: %s. Digest %02d:00 UTC, scan every %ds.",
            sum(len(wl.symbols) for wl in self.watchlists), len(self.watchlists),
            self.timeframe, ", ".join(d.name for d in self.detectors),
            self.digest_hour_utc, interval_seconds,
        )
        while True:
            try:
                self.scan_once()
                self.maybe_send_digest()
            except Exception as e:
                log.exception("monitor cycle crashed: %s", e)
            if once:
                break
            time.sleep(interval_seconds)


def run_monitor_forever(
    watchlists: list[Watchlist],
    notifier: Notifier,
    rsi_length: int = 14,
    oversold_threshold: float = 30.0,
    overbought_threshold: float = 70.0,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    timeframe: str = "1d",
    digest_hour_utc: int = 8,
    interval_seconds: int = 600,
    state_path: str | Path = ".rsi_monitor_state.json",
    once: bool = False,
) -> None:
    """Thin entry point: choose the active detectors, build the Monitor, run it.

    This is the one place that decides *which* detectors are active — to add a
    new signal, write a Detector and append it to this list."""
    detectors: list[Detector] = [
        RsiZoneDetector(rsi_length, oversold_threshold, overbought_threshold),
        MacdCrossDetector(macd_fast, macd_slow, macd_signal),
    ]
    Monitor(
        watchlists, notifier, detectors,
        timeframe=timeframe, digest_hour_utc=digest_hour_utc, state_path=state_path,
    ).run(interval_seconds=interval_seconds, once=once)
