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
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import ccxt
import pandas as pd

from .config import MonitorConfig
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
        watchlist_provider: Callable[[], list[Watchlist]] | None = None,
    ):
        self.watchlists      = watchlists
        # Optional: called at the start of each scan to replace the watchlists
        # (e.g. with the coins currently held on Revolut X).
        self.watchlist_provider = watchlist_provider
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
        if not self._refresh_watchlists():
            return
        for wl in self.watchlists:
            exchange = self._exchange_for(wl)
            if exchange is None:
                continue
            for base in wl.symbols:
                self._scan_symbol(exchange, wl, base)
        self._prune_removed_symbols()
        self._save_state()

    def _refresh_watchlists(self) -> bool:
        """Ask the provider (if any) for fresh watchlists. On failure keep the
        last good ones; with none known yet, skip the scan entirely — pruning
        against an empty list would wipe every detector's memory."""
        if self.watchlist_provider is None:
            return True
        try:
            self.watchlists = self.watchlist_provider()
            return True
        except Exception as e:
            log.error("could not refresh watchlists (%s) — %s", e,
                      "keeping the previous ones" if self.watchlists else "skipping this scan")
            return bool(self.watchlists)

    def _prune_removed_symbols(self) -> None:
        """Drop state for symbols no longer in any watchlist, so it can't grow
        forever or linger in the digest after you remove a coin."""
        live = {
            f"{wl.exchange}:{base}/{wl.quote}"
            for wl in self.watchlists for base in wl.symbols
        }
        for d in self.detectors:
            d.prune(live)

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
            # A coin someone actually holds deserves a visible log line.
            level = logging.INFO if base in wl.amounts else logging.DEBUG
            log.log(level, "skip %s (not listed on %s)", symbol, wl.exchange)
            return
        key = f"{wl.exchange}:{symbol}"
        try:
            close = self._fetch_close(exchange, symbol)
            if close is not None:
                self._run_detectors(key, base, wl, close)
        except ccxt.BaseError as e:
            log.warning("ccxt error %s: %s", symbol, e)
        except Exception as e:
            log.exception("error %s: %s", symbol, e)
        # respect the exchange rate limit (rateLimit is ms; default if unset)
        time.sleep((exchange.rateLimit or 1000) / 1000)

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

    def _run_detectors(self, key: str, base: str, wl: Watchlist,
                       close: pd.Series) -> None:
        """Run each detector on one symbol and send whatever alerts they raise."""
        fired = False
        for d in self.detectors:
            for alert in d.update(key, close):
                self._send_alert(base, wl, alert)
                fired = True
        # Save right after an alert so a crash can't cause us to re-send it.
        if fired:
            self._save_state()

    def _send_alert(self, base: str, wl: Watchlist, a: Alert) -> None:
        """Wrap a detector's Alert with the symbol/exchange context and send it."""
        symbol = f"{base}/{wl.quote}"
        log.info("ALERT  %s  %s", symbol, a.title)
        held = (f"\nYou hold {wl.amounts[base].normalize():f} {base}"
                if base in wl.amounts else "")
        self.notifier.send(
            f"{a.emoji} *{symbol}* {a.title}\n"
            f"on *{wl.exchange}* ({self.timeframe})\n"
            f"{a.detail}{held}"
        )

    # --------------------------------------------------------------- digest
    def maybe_send_digest(self) -> None:
        """Send the daily digest once, at/after digest_hour_utc each day."""
        now = datetime.now(UTC)
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


def build_detectors(config: MonitorConfig) -> list[Detector]:
    """Choose which detectors are active. To add a new signal, write a Detector
    and append it here — this is the only place that decides the active set."""
    return [
        RsiZoneDetector(config.rsi_length,
                        config.oversold_threshold, config.overbought_threshold),
        MacdCrossDetector(config.macd_fast, config.macd_slow, config.macd_signal),
    ]


def run_monitor_forever(
    watchlists: list[Watchlist],
    notifier: Notifier,
    config: MonitorConfig,
    once: bool = False,
    watchlist_provider: Callable[[], list[Watchlist]] | None = None,
) -> None:
    """Thin entry point: build the detectors and the Monitor from config, run it."""
    monitor = Monitor(
        watchlists, notifier, build_detectors(config),
        timeframe=config.timeframe,
        digest_hour_utc=config.digest_hour_utc,
        state_path=config.state_path,
        watchlist_provider=watchlist_provider,
    )
    monitor.run(interval_seconds=config.interval_seconds, once=once)
