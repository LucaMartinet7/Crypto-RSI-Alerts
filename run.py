#!/usr/bin/env python3
"""
Entry point.

Local:          python3 run.py           (loops forever, reads .env)
GitHub Actions: python3 run.py --once    (single scan then exits, reads env vars)
"""

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from alerter import TelegramNotifier, run_forever  # noqa: E402
from watchlists import WATCHLISTS                   # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan and exit (used by GitHub Actions)",
    )
    args = parser.parse_args()

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-7s  %(name)-18s  %(message)s",
    )

    scan_interval = int(os.environ.get("SCAN_INTERVAL", "900"))
    notifier = TelegramNotifier()
    run_forever(WATCHLISTS, notifier, interval_seconds=scan_interval, once=args.once)


if __name__ == "__main__":
    main()
