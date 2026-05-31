"""
RSI band monitor — the heart of the app.

It watches the *live* RSI of the in-progress candle (df.iloc[-1]) so that, on a
1d timeframe, the RSI still moves throughout the day as price moves — today's
"close" is just the current price until the candle closes at 00:00 UTC.

Every symbol is always in one of three "zones":
    oversold     RSI below the low threshold  (default < 30)
    neutral      RSI between the two thresholds
    overbought   RSI above the high threshold (default > 70)

It produces:

  Instant alerts (the moment a symbol moves from one zone to another):
    🔻 crossed DOWN into oversold      (RSI fell under 30)
    🟢 recovered back up out of oversold (RSI climbed back over 30)
    📈 crossed UP into overbought      (RSI rose over 70)
    🔵 cooled back down out of overbought (RSI dropped back under 70)

  Daily digest (once per day at digest_hour_utc) — four lists:
    currently oversold, recovered-since-last-digest,
    currently overbought, cooled-off-since-last-digest.

State (each symbol's current zone, plus who recovered/cooled today) is held in
memory and mirrored to a JSON file on disk so a process/VM restart doesn't lose
it or re-spam alerts. Designed to run as a long-lived process (e.g. on a small
VM), not as a one-shot job.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
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

# The three zones a symbol can be in.
OVERSOLD = "oversold"
NEUTRAL = "neutral"
OVERBOUGHT = "overbought"


@dataclass
class _State:
    """Everything we remember between scans (and save to disk)."""
    # key "exchange:SYMBOL" -> its current zone (oversold / neutral / overbought)
    zone: dict[str, str] = field(default_factory=dict)
    # keys that left the OVERSOLD zone (climbed back over 30) since last digest
    recovered_today: set[str] = field(default_factory=set)
    # keys that left the OVERBOUGHT zone (dropped back under 70) since last digest
    cooled_today: set[str] = field(default_factory=set)
    # date (UTC) of the last digest we sent, so we send at most one per day
    last_digest_date: date | None = None

    @classmethod
    def empty(cls) -> "_State":
        return cls()


class RsiBandMonitor:
    """Tracks each symbol's live-RSI zone and emits crossing + digest alerts.

    The symbol universe is taken from the given watchlists (their exchange,
    quote and symbols). The candle timeframe and RSI settings are set here, once,
    for all of them.
    """

    def __init__(
        self,
        watchlists: list[Watchlist],
        notifier: Notifier,
        rsi_length: int = 14,
        oversold_threshold: float = 30.0,
        overbought_threshold: float = 70.0,
        timeframe: str = "1d",
        digest_hour_utc: int = 8,
        state_path: str | Path = ".rsi_monitor_state.json",
    ):
        self.watchlists           = watchlists
        self.notifier             = notifier
        self.rsi_length           = rsi_length
        self.oversold_threshold   = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self.timeframe            = timeframe
        self.digest_hour_utc      = digest_hour_utc
        self.state_path           = Path(state_path)
        self.state                = self._load_state()

    # ------------------------------------------------------------------ state
    def _load_state(self) -> _State:
        """Read saved state from disk on startup. If the file is missing or
        unreadable, start fresh (the monitor will simply re-learn each symbol's
        zone on the first scan instead of crashing)."""
        if not self.state_path.exists():
            return _State.empty()
        try:
            raw = json.loads(self.state_path.read_text())
            last = raw.get("last_digest_date")
            return _State(
                zone=dict(raw.get("zone", {})),
                recovered_today=set(raw.get("recovered_today", [])),
                cooled_today=set(raw.get("cooled_today", [])),
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
                "zone": self.state.zone,
                "recovered_today": sorted(self.state.recovered_today),
                "cooled_today": sorted(self.state.cooled_today),
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
    def _zone(self, r: float) -> str:
        """Which zone an RSI value falls in."""
        if r < self.oversold_threshold:
            return OVERSOLD
        if r > self.overbought_threshold:
            return OVERBOUGHT
        return NEUTRAL

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
        """One pass over every symbol: detect zone changes and fire alerts."""
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
        """Compare a symbol's current RSI zone to its previous one and, if it
        just moved between zones, fire the matching alert."""
        new = self._zone(r)
        prev = self.state.zone.get(key)  # None == we've never seen it before

        if prev is None:
            # First time we've ever seen this symbol: just record its zone, with
            # no alert. Otherwise a restart would alert on every coin that merely
            # happens to be oversold/overbought right now.
            self.state.zone[key] = new
            return

        if new == prev:
            return  # same zone as last scan — nothing to announce

        # A genuine zone change happened this scan.
        lo, hi = self.oversold_threshold, self.overbought_threshold
        if new == OVERSOLD:
            self._alert(symbol, wl, r, "🔻", f"crossed UNDER RSI {lo:g} (oversold)")
        elif new == OVERBOUGHT:
            self._alert(symbol, wl, r, "📈", f"crossed OVER RSI {hi:g} (overbought)")
        elif prev == OVERSOLD:                       # oversold -> neutral
            self._alert(symbol, wl, r, "🟢", f"recovered back over RSI {lo:g}")
            self.state.recovered_today.add(key)
        elif prev == OVERBOUGHT:                     # overbought -> neutral
            self._alert(symbol, wl, r, "🔵", f"cooled back under RSI {hi:g}")
            self.state.cooled_today.add(key)

        self.state.zone[key] = new
        # Save right away: zone changes are rare, so this is cheap, and it means
        # a crash just after an alert can't cause us to re-send it on next start.
        self._save_state()

    # ---------------------------------------------------------------- alerts
    def _alert(self, symbol: str, wl: Watchlist, r: float,
               emoji: str, action: str) -> None:
        """Send one instant alert message (and log it)."""
        log.info("ALERT  %s  %s  RSI=%.2f", symbol, action, r)
        self.notifier.send(
            f"{emoji} *{symbol}* {action}\n"
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
        self.state.cooled_today.clear()
        self._save_state()

    def _send_digest(self, today: date) -> None:
        """Build and send the once-a-day summary: who is oversold/overbought
        right now, and who recovered/cooled off since the last digest."""
        def label(key: str) -> str:
            # "binance:BTC/USDT" -> "BTC/USDT (binance)"
            exch, sym = key.split(":", 1)
            return f"{sym} ({exch})"

        def block(keys: list[str]) -> str:
            return "\n".join(f"• {label(k)}" for k in keys) if keys else "_none_"

        oversold   = sorted(k for k, z in self.state.zone.items() if z == OVERSOLD)
        overbought = sorted(k for k, z in self.state.zone.items() if z == OVERBOUGHT)
        recovered  = sorted(self.state.recovered_today)
        cooled     = sorted(self.state.cooled_today)
        lo, hi = self.oversold_threshold, self.overbought_threshold

        log.info("DIGEST  %d oversold, %d recovered, %d overbought, %d cooled",
                 len(oversold), len(recovered), len(overbought), len(cooled))
        self.notifier.send(
            f"🗓️ *Daily RSI digest* — {today:%Y-%m-%d} {self.digest_hour_utc:02d}:00 UTC\n"
            f"_RSI{self.rsi_length} on {self.timeframe} • oversold <{lo:g} • overbought >{hi:g}_\n\n"
            f"🔻 *Currently oversold (under {lo:g}):*\n{block(oversold)}\n\n"
            f"🟢 *Recovered (back over {lo:g}) since last digest:*\n{block(recovered)}\n\n"
            f"📈 *Currently overbought (over {hi:g}):*\n{block(overbought)}\n\n"
            f"🔵 *Cooled off (back under {hi:g}) since last digest:*\n{block(cooled)}"
        )


def run_monitor_forever(
    watchlists: list[Watchlist],
    notifier: Notifier,
    rsi_length: int = 14,
    oversold_threshold: float = 30.0,
    overbought_threshold: float = 70.0,
    timeframe: str = "1d",
    digest_hour_utc: int = 8,
    interval_seconds: int = 600,
    state_path: str | Path = ".rsi_monitor_state.json",
    once: bool = False,
) -> None:
    """Main loop for the RSI band monitor. Intended to run continuously."""
    monitor = RsiBandMonitor(
        watchlists, notifier,
        rsi_length=rsi_length,
        oversold_threshold=oversold_threshold,
        overbought_threshold=overbought_threshold,
        timeframe=timeframe, digest_hour_utc=digest_hour_utc, state_path=state_path,
    )
    total_symbols = sum(len(wl.symbols) for wl in watchlists)
    log.info(
        "RSI band monitor: %d symbols across %d watchlist(s), "
        "RSI%d %s, oversold <%g / overbought >%g, digest %02d:00 UTC, scan every %ds.",
        total_symbols, len(watchlists), rsi_length, timeframe,
        oversold_threshold, overbought_threshold, digest_hour_utc, interval_seconds,
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
