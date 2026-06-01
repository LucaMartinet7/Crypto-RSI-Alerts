"""
Monitor — the orchestrator, and the heart of the app.

It loops forever. On each pass it:
    1. downloads recent candles for every coin in your watchlists,
    2. hands the closing prices to each *detector* (see alerter/signals/),
    3. sends a Telegram message for any alert a detector returns,
    4. once a day, sends a digest summarising the current state.

The monitor itself knows nothing about RSI or MACD — that logic lives in the
detectors. It just fetches data, runs whatever detectors it was given, sends
messages, and saves state. To add a new kind of signal you write a detector;
you don't touch this file.

State (every detector's per-symbol memory + the last digest date) is mirrored to
a JSON file so a restart doesn't lose it or re-send alerts. Designed to run as a
long-lived process (e.g. on a small VM), not as a one-shot job.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd

from .exchanges import get_exchange
from .notifier import Notifier
from .signals import Alert, Detector, MacdCrossDetector, RsiZoneDetector
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
        self.state_path      = Path(state_path)
        # Fetch enough history for the hungriest detector.
        self._min_candles    = max(d.min_candles for d in detectors)
        self.last_digest_date: date | None = None
        self._load_state()

    # ------------------------------------------------------------------ state
    def _load_state(self) -> None:
        """Load saved state on startup. Each detector picks out its own keys.
        If the file is missing or unreadable we just start fresh (detectors
        re-learn each symbol on the first scan instead of crashing)."""
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text())
        except Exception as e:
            log.warning("Could not read state file %s (%s) — starting fresh.",
                        self.state_path, e)
            return
        for d in self.detectors:
            d.load_state(raw)
        last = raw.get("last_digest_date")
        self.last_digest_date = date.fromisoformat(last) if last else None

    def _save_state(self) -> None:
        """Write all detectors' state (plus the digest date) to one JSON file,
        atomically so a crash mid-write can't corrupt it."""
        data: dict = {
            "last_digest_date":
                self.last_digest_date.isoformat() if self.last_digest_date else None,
        }
        for d in self.detectors:
            data.update(d.state_dict())
        try:
            tmp = self.state_path.with_name(self.state_path.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            os.replace(tmp, self.state_path)   # atomic on POSIX
        except Exception as e:
            log.error("Could not write state file %s: %s", self.state_path, e)

    # ------------------------------------------------------------------ fetch
    def _fetch_close(self, exchange: ccxt.Exchange, symbol: str) -> pd.Series | None:
        """Download recent candles and return just the closing-price column.
        Returns None if there isn't enough history. One fetch feeds every
        detector, so we never hit the exchange more than once per symbol."""
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=self.timeframe,
                                     limit=_FETCH_LIMIT)
        if len(ohlcv) < self._min_candles:
            return None
        return pd.DataFrame(
            ohlcv, columns=["ts", "open", "high", "low", "close", "volume"]
        )["close"]

    # ------------------------------------------------------------------ scan
    def scan_once(self) -> None:
        """One pass over every symbol: fetch prices, run every detector, send
        any alerts they raise."""
        for wl in self.watchlists:
            try:
                exchange = get_exchange(wl.exchange)
            except Exception as e:
                log.error("could not load exchange %s (%s) — skipping watchlist %r",
                          wl.exchange, e, wl.name)
                continue
            markets = exchange.markets
            for base in wl.symbols:
                symbol = f"{base}/{wl.quote}"
                if symbol not in markets:
                    log.debug("skip %s (not listed on %s)", symbol, wl.exchange)
                    continue
                key = f"{wl.exchange}:{symbol}"
                try:
                    close = self._fetch_close(exchange, symbol)
                    if close is None:
                        continue
                    fired = False
                    for d in self.detectors:
                        for alert in d.update(key, close):
                            self._send_alert(symbol, wl, alert)
                            fired = True
                    # Save right after an alert so a crash can't re-send it.
                    if fired:
                        self._save_state()
                except ccxt.BaseError as e:
                    log.warning("ccxt error %s: %s", symbol, e)
                except Exception as e:
                    log.exception("error %s: %s", symbol, e)
                time.sleep(exchange.rateLimit / 1000)   # respect rate limits
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
    """Build the detectors, then run the monitor loop. Intended to run forever.

    This is the one place that decides *which* detectors are active. To add a
    new signal, write a Detector and append it to this list."""
    detectors: list[Detector] = [
        RsiZoneDetector(rsi_length, oversold_threshold, overbought_threshold),
        MacdCrossDetector(macd_fast, macd_slow, macd_signal),
    ]
    monitor = Monitor(
        watchlists, notifier, detectors,
        timeframe=timeframe, digest_hour_utc=digest_hour_utc, state_path=state_path,
    )
    log.info(
        "Monitor: %d symbols across %d watchlist(s), %s candles. "
        "Detectors: %s. Digest %02d:00 UTC, scan every %ds.",
        sum(len(wl.symbols) for wl in watchlists), len(watchlists), timeframe,
        ", ".join(d.name for d in detectors), digest_hour_utc, interval_seconds,
    )

    while True:
        try:
            monitor.scan_once()
            monitor.maybe_send_digest()
        except Exception as e:
            log.exception("monitor cycle crashed: %s", e)
        if once:
            break
        time.sleep(interval_seconds)
