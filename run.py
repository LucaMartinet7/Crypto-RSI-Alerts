#!/usr/bin/env python3
"""
Entry point — the file you actually run. It wires your config (watchlists.py)
to the RSI band monitor and starts it.

The monitor watches the LIVE RSI of every coin and sends an alert the moment a
coin crosses under/over the threshold, plus a once-a-day summary. See
alerter/monitor.py for the details.

How to run it:
    python3 run.py            run forever (this is what the VM service runs)
    python3 run.py --once     run a single scan then exit (handy for testing)

Settings come from a local ".env" file (loaded below). Relevant variables:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   where alerts are sent
    RSI_LENGTH (14)                        RSI look-back period
    RSI_THRESHOLD (30)                     oversold line (alerts when RSI drops under)
    RSI_HIGH_THRESHOLD (70)                overbought line (alerts when RSI rises over)
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

from alerter import TelegramNotifier, run_monitor_forever  # noqa: E402
from watchlists import WATCHLISTS                          # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan then exit (handy for testing).",
    )
    # The monitor is now the only engine, but the production systemd service
    # still launches "run.py --monitor", so we accept (and ignore) the flag.
    parser.add_argument(
        "--monitor",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-7s  %(name)-18s  %(message)s",
    )

    notifier = TelegramNotifier()
    run_monitor_forever(
        WATCHLISTS,
        notifier,
        rsi_length=int(os.environ.get("RSI_LENGTH", "14")),
        oversold_threshold=float(os.environ.get("RSI_THRESHOLD", "30")),
        overbought_threshold=float(os.environ.get("RSI_HIGH_THRESHOLD", "70")),
        timeframe=os.environ.get("MONITOR_TIMEFRAME", "1d"),
        digest_hour_utc=int(os.environ.get("DIGEST_HOUR_UTC", "8")),
        interval_seconds=int(os.environ.get("MONITOR_INTERVAL", "600")),
        state_path=os.environ.get("MONITOR_STATE_FILE", ".rsi_monitor_state.json"),
        once=args.once,
    )


if __name__ == "__main__":
    main()
