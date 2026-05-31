"""
==========================================================================
YOUR CONFIG — edit this file to add/remove coins.
==========================================================================

A Watchlist bundles:
  - name       human-readable label, shown in alerts and logs
  - exchange   which ccxt exchange to pull data from
               examples: "binance", "bybit", "kucoin", "okx", "mexc", "coinbase"
  - quote      quote currency (the "/USDT" part of "BTC/USDT")
  - symbols    base assets to watch

The RSI monitor reads every Watchlist on each scan. The RSI settings
(length, threshold, timeframe, scan interval, digest time) are global and live
in .env — see run.py for the full list.

Add a new watchlist by appending another Watchlist(...) to the list.
Multiple watchlists run on every scan cycle, in order.
"""

from alerter import Watchlist

WATCHLISTS: list[Watchlist] = [

    # Main: 58 symbols on Binance.
    # (Binance geo-blocks US IPs, so the monitor VM must run in a non-US region.)
    Watchlist(
        name="binance-main",
        exchange="binance",
        quote="USDT",
        symbols=[
            "1INCH", "AAVE",  "ADA",  "AGLD", "AI",   "ALGO", "APT",  "ATOM",
            "AVAX",  "AXS",   "BAL",  "BCH",  "BNB",  "BNT",  "BONK", "BTC",
            "CELO",  "COTI",  "CRV",  "DASH", "DOGE", "DOT",  "ETC",  "ETH",
            "FET",   "FIDA",  "FLOW", "FORTH","GALA", "HBAR", "HFT",  "IDEX",
            "IMX",   "IO",    "IOTX", "JASMY","KAVA", "KNC",  "LINK", "LRC",
            "LTC",   "MANA",  "POL",  "RENDER","SAND","SHIB", "SOL",  "SUI",
            "SUSHI", "SXT",   "TIA",  "UNI",  "VET",  "WLFI", "XLM",  "XRP",
            "XTZ",   "ZRX",
        ],
    ),

    # The 8 long-tail tokens not on Binance — picked up via Bybit instead.
    # (Some of these may also be missing on Bybit — they'll just log and skip.)
    Watchlist(
        name="bybit-longtail",
        exchange="bybit",
        quote="USDT",
        symbols=["AIOZ", "AKT", "CRO", "FLR", "GODS", "LMWR", "MEW", "ZKJ"],
    ),
]
