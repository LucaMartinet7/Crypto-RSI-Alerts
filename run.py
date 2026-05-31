#!/usr/bin/env python3
"""
Entry point — the file you actually run. It wires together your config
(watchlists.py) with one of the two engines and starts it.

Two engines:
  • RSI band monitor (what runs in production) — watches the LIVE RSI and
    sends an alert the moment a coin crosses under/over the threshold, plus a
    once-a-day summary. See alerter/monitor.py.
  • Strategy scanner (the simpler original) — checks each closed candle against
    a Strategy. See alerter/scanner.py.

How to run it:
    python3 run.py --monitor      live RSI monitor, runs forever (production)
    python3 run.py                strategy scanner, runs forever
    python3 run.py --once         run a single pass then exit (handy for tests)
    python3 run.py --monitor --once   one monitor pass then exit

Settings come from a local ".env" file (loaded below). Relevant variables:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   where alerts are sent
    RSI_LENGTH (14), RSI_THRESHOLD (30)    the RSI settings
    MONITOR_TIMEFRAME (1d)                 candle size the RSI is computed on
    DIGEST_HOUR_UTC (8)                    when the daily summary is sent
    MONITOR_INTERVAL (600)                 seconds between scans
    LOG_LEVEL (INFO)                       how chatty the logs are
"""

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from alerter import TelegramNotifier, run_forever, run_monitor_forever  # noqa: E402
from watchlists import WATCHLISTS                                       # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan and exit (used by GitHub Actions)",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Run the live RSI band monitor (cross-under / cross-over alerts "
             "+ daily digest) instead of the strategy scanner.",
    )
    args = parser.parse_args()

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-7s  %(name)-18s  %(message)s",
    )

    notifier = TelegramNotifier()

    if args.monitor:
        run_monitor_forever(
            WATCHLISTS,
            notifier,
            rsi_length=int(os.environ.get("RSI_LENGTH", "14")),
            threshold=float(os.environ.get("RSI_THRESHOLD", "30")),
            timeframe=os.environ.get("MONITOR_TIMEFRAME", "1d"),
            digest_hour_utc=int(os.environ.get("DIGEST_HOUR_UTC", "8")),
            interval_seconds=int(os.environ.get("MONITOR_INTERVAL", "600")),
            state_path=os.environ.get("MONITOR_STATE_FILE", ".rsi_monitor_state.json"),
            once=args.once,
        )
        return

    scan_interval = int(os.environ.get("SCAN_INTERVAL", "900"))
    run_forever(WATCHLISTS, notifier, interval_seconds=scan_interval, once=args.once)


if __name__ == "__main__":
    main()
