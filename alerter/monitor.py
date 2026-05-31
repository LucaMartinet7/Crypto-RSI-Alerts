"""
RSI band monitor — the heart of the app.

It watches the *live* RSI of the in-progress candle (df.iloc[-1]) so that, on a
1d timeframe, the RSI still moves throughout the day as price moves — today's
"close" is just the current price until the candle closes at 00:00 UTC.

It produces:

  Instant alerts (the moment a transition happens, one per genuine flip):
    - a symbol crosses DOWN through the threshold  (e.g. RSI < 30)
    - a symbol crosses back UP through the threshold (recovered to/over 30)

  Daily digest (once per day at digest_hour_utc):
    - List 1: everything currently under the threshold (oversold right now)
    - List 2: everything that dipped under the threshold and has since
              recovered back over it during the day

State (who is currently oversold, who recovered today) is held in memory and
mirrored to a JSON file on disk so a process/VM restart doesn't lose it or
re-spam alerts. Designed to run as a long-lived process (e.g. on a small VM),
not as a one-shot job.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd

from .exchanges import get_exchange
from .indicators import rsi
from .notifier import Notifier
from .watchlist import Watchlist

log = logging.getLogger("alerter.monitor")

# How much daily history to pull. Wilder's RSI needs a long warm-up to match
# TradingView closely, so we fetch generously.
_FETCH_LIMIT = 300


@dataclass
class _State:
    """Persisted monitor state."""
    # key "exchange:SYMBOL" -> is it currently below the threshold?
    oversold: dict[str, bool]
    # keys that dipped under and recovered since the last digest
    recovered_today: set[str]
    # date (UTC) of the last digest we sent, so we send at most one per day
    last_digest_date: date | None

    @classmethod
    def empty(cls) -> "_State":
        return cls(oversold={}, recovered_today=set(), last_digest_date=None)


class RsiBandMonitor:
    """Tracks live RSI relative to a threshold and emits crossing + digest alerts.

    The symbol universe is taken from the given watchlists (their exchange,
    quote and symbols). The watchlists' own timeframe/strategy are ignored —
    this monitor imposes its own ``timeframe`` and RSI settings.
    """

    def __init__(
        self,
        watchlists: list[Watchlist],
        notifier: Notifier,
        rsi_length: int = 14,
        threshold: float = 30.0,
        timeframe: str = "1d",
        digest_hour_utc: int = 8,
        state_path: str | Path = ".rsi_monitor_state.json",
    ):
        self.watchlists      = watchlists
        self.notifier        = notifier
        self.rsi_length      = rsi_length
        self.threshold       = threshold
        self.timeframe       = timeframe
        self.digest_hour_utc = digest_hour_utc
        self.state_path       = Path(state_path)
        self.state            = self._load_state()

    # ------------------------------------------------------------------ state
    def _load_state(self) -> _State:
        """Read saved state from disk on startup. If the file is missing or
        unreadable, start fresh (the monitor will simply re-learn each symbol's
        state on the first scan instead of crashing)."""
        if not self.state_path.exists():
            return _State.empty()
        try:
            raw = json.loads(self.state_path.read_text())
            last = raw.get("last_digest_date")
            return _State(
                oversold=dict(raw.get("oversold", {})),
                recovered_today=set(raw.get("recovered_today", [])),
                last_digest_date=date.fromisoformat(last) if last else None,
            )
        except Exception as e:
            log.warning("Could not read state file %s (%s) — starting fresh.",
                        self.state_path, e)
            return _State.empty()

    def _save_state(self) -> None:
        """Write the current state to disk so a restart picks up where we left
        off (and we don't re-send alerts)."""
        try:
            data = json.dumps({
                "oversold": self.state.oversold,
                "recovered_today": sorted(self.state.recovered_today),
                "last_digest_date": (
                    self.state.last_digest_date.isoformat()
                    if self.state.last_digest_date else None
                ),
            }, indent=2)
            # Write atomically: a crash mid-write leaves the old file intact
            # (os.replace is atomic on POSIX) rather than a truncated JSON file.
            tmp = self.state_path.with_name(self.state_path.name + ".tmp")
            tmp.write_text(data)
            os.replace(tmp, self.state_path)
        except Exception as e:
            log.error("Could not write state file %s: %s", self.state_path, e)

    # -------------------------------------------------------------- live RSI
    def _live_rsi(self, exchange: ccxt.Exchange, symbol: str) -> float | None:
        """RSI of the in-progress candle (df.iloc[-1]). None if unavailable."""
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=self.timeframe,
                                     limit=_FETCH_LIMIT)
        if len(ohlcv) < self.rsi_length + 2:
            return None
        close = pd.DataFrame(
            ohlcv, columns=["ts", "open", "high", "low", "close", "volume"]
        )["close"]
        r = rsi(close, self.rsi_length).iloc[-1]
        return None if pd.isna(r) else float(r)

    # ------------------------------------------------------------------ scan
    def scan_once(self) -> None:
        """One pass over every symbol: detect transitions and fire alerts."""
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
                    r = self._live_rsi(exchange, symbol)
                    if r is None:
                        continue
                    self._handle(key, symbol, wl, r)
                except ccxt.BaseError as e:
                    log.warning("ccxt error %s: %s", symbol, e)
                except Exception as e:
                    log.exception("error %s: %s", symbol, e)
                time.sleep(exchange.rateLimit / 1000)
        self._save_state()

    def _handle(self, key: str, symbol: str, wl: Watchlist, r: float) -> None:
        """Compare one symbol's live RSI against its previous state and, if it
        just crossed the threshold, fire the matching alert."""
        now_oversold = r < self.threshold
        prev = self.state.oversold.get(key)  # None == we've never seen it before

        if prev is None:
            # First time we've ever seen this symbol: just record where it
            # stands, with no alert. Otherwise a restart would alert on every
            # coin that merely happens to be oversold right now.
            self.state.oversold[key] = now_oversold
            return

        if now_oversold == prev:
            return  # no change since the last scan — nothing to announce

        # A genuine crossing happened this scan.
        if now_oversold:
            self._alert_cross_under(symbol, wl, r)          # fell under 30
        else:
            self._alert_cross_over(symbol, wl, r)           # climbed back over 30
            self.state.recovered_today.add(key)

        self.state.oversold[key] = now_oversold
        # Save right away: crossings are rare, so this is cheap, and it means a
        # crash just after an alert can't cause us to re-send it on next start.
        self._save_state()

    # ---------------------------------------------------------------- alerts
    def _alert_cross_under(self, symbol: str, wl: Watchlist, r: float) -> None:
        log.info("CROSS UNDER  %s  RSI=%.2f", symbol, r)
        self.notifier.send(
            f"🔻 *{symbol}* crossed UNDER RSI {self.threshold:g}\n"
            f"on *{wl.exchange}* ({self.timeframe})\n"
            f"RSI{self.rsi_length} = `{r:.2f}`"
        )

    def _alert_cross_over(self, symbol: str, wl: Watchlist, r: float) -> None:
        log.info("CROSS OVER   %s  RSI=%.2f", symbol, r)
        self.notifier.send(
            f"🟢 *{symbol}* recovered back over RSI {self.threshold:g}\n"
            f"on *{wl.exchange}* ({self.timeframe})\n"
            f"RSI{self.rsi_length} = `{r:.2f}`"
        )

    # --------------------------------------------------------------- digest
    def maybe_send_digest(self) -> None:
        """Send the daily digest once, at/after digest_hour_utc each day."""
        now = datetime.now(timezone.utc)
        today = now.date()
        already_sent_today = (
            self.state.last_digest_date is not None
            and self.state.last_digest_date >= today
        )
        if now.hour < self.digest_hour_utc or already_sent_today:
            return

        self._send_digest(today)
        self.state.last_digest_date = today
        self.state.recovered_today.clear()
        self._save_state()

    def _send_digest(self, today: date) -> None:
        """Build and send the once-a-day summary message: who is oversold right
        now, and who has recovered back over the threshold since the last one."""
        def label(key: str) -> str:
            # "binance:BTC/USDT" -> "BTC/USDT (binance)"
            exch, sym = key.split(":", 1)
            return f"{sym} ({exch})"

        oversold = sorted(k for k, v in self.state.oversold.items() if v)
        recovered = sorted(self.state.recovered_today)

        under_block = (
            "\n".join(f"• {label(k)}" for k in oversold) if oversold else "_none_"
        )
        recovered_block = (
            "\n".join(f"• {label(k)}" for k in recovered) if recovered else "_none_"
        )

        log.info("DIGEST  %d oversold, %d recovered", len(oversold), len(recovered))
        self.notifier.send(
            f"🗓️ *Daily RSI digest* — {today:%Y-%m-%d} {self.digest_hour_utc:02d}:00 UTC\n"
            f"_RSI{self.rsi_length} on {self.timeframe}, threshold {self.threshold:g}_\n\n"
            f"*Currently under {self.threshold:g} (oversold):*\n{under_block}\n\n"
            f"*Recovered (dipped under {self.threshold:g} → back over) since last digest:*\n"
            f"{recovered_block}"
        )


def run_monitor_forever(
    watchlists: list[Watchlist],
    notifier: Notifier,
    rsi_length: int = 14,
    threshold: float = 30.0,
    timeframe: str = "1d",
    digest_hour_utc: int = 8,
    interval_seconds: int = 600,
    state_path: str | Path = ".rsi_monitor_state.json",
    once: bool = False,
) -> None:
    """Main loop for the RSI band monitor. Intended to run continuously."""
    monitor = RsiBandMonitor(
        watchlists, notifier,
        rsi_length=rsi_length, threshold=threshold, timeframe=timeframe,
        digest_hour_utc=digest_hour_utc, state_path=state_path,
    )
    total_symbols = sum(len(wl.symbols) for wl in watchlists)
    log.info(
        "RSI band monitor: %d symbols across %d watchlist(s), "
        "RSI%d %s, threshold %g, digest %02d:00 UTC, scan every %ds.",
        total_symbols, len(watchlists), rsi_length, timeframe,
        threshold, digest_hour_utc, interval_seconds,
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
