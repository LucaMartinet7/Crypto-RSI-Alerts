#!/usr/bin/env python3
"""
Entry point — the file you actually run. It wires your config (watchlists.py)
to the monitor and starts it.

The monitor watches the live RSI and MACD of every coin and sends an alert the
moment a signal fires, plus a once-a-day summary. See alerter/monitor.py.

How to run it:
    python3 run.py            run forever (this is what the VM service runs)
    python3 run.py --once     run a single scan then exit (handy for testing)

All settings come from a local ".env" file (see MonitorConfig.from_env in
alerter/config.py for the full list of variables and their defaults).
"""

import argparse
import logging
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

import os  # noqa: E402

from alerter import (  # noqa: E402
    MonitorConfig,
    TelegramNotifier,
    run_monitor_forever,
)
from alerter.exchanges import register_exchange  # noqa: E402
from alerter.holdings import holdings_provider  # noqa: E402
from alerter.lockfile import AlreadyRunning, single_instance  # noqa: E402
from alerter.revx import RevolutXClient  # noqa: E402
from watchlists import WATCHLISTS  # noqa: E402

log = logging.getLogger("alerter.run")


def _install_signal_handlers() -> None:
    """Turn SIGTERM (what `systemctl stop` sends) into a clean exit so the
    single-instance lock is released via the context manager's `finally`."""
    def handler(signum, _frame):
        log.info("received signal %s — shutting down.", signum)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, handler)


def _watchlists_from_env():
    """With REVX_API_KEY set, watch the coins held on Revolut X (refreshed every
    scan); otherwise the fixed list in watchlists.py."""
    api_key = os.environ.get("REVX_API_KEY", "").strip()
    if not api_key:
        return WATCHLISTS, None
    key_file = os.environ.get("REVX_PRIVATE_KEY_FILE", "").strip()
    if not key_file:
        sys.exit("REVX_API_KEY is set but REVX_PRIVATE_KEY_FILE (path to private.pem) is not.")
    try:
        pem = Path(key_file).expanduser().read_bytes()
        client = RevolutXClient(api_key, pem)
    except (OSError, ValueError) as e:
        sys.exit(f"Revolut X key problem ({key_file}): {e}")
    register_exchange("revolutx", client)
    log.info("Watchlist: every coin held on Revolut X "
             "(prices from Revolut X, else Binance, else Bybit).")
    return [], holdings_provider(client)


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto RSI/MACD alert monitor.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan then exit (handy for testing).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s  %(levelname)-7s  %(name)-18s  %(message)s",
    )
    _install_signal_handlers()

    config = MonitorConfig.from_env()
    notifier = TelegramNotifier()
    watchlists, provider = _watchlists_from_env()

    try:
        # Refuse to start a second copy — two monitors would double-send alerts
        # and clobber the shared state file.
        with single_instance(config.lock_path):
            run_monitor_forever(watchlists, notifier, config, once=args.once,
                                watchlist_provider=provider)
    except AlreadyRunning as e:
        log.error("Not starting: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
