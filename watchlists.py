"""
==========================================================================
YOUR CONFIG — edit this file to add/remove watchlists.
==========================================================================

A Watchlist bundles:
  - name       human-readable label, shown in alerts and logs
  - exchange   which ccxt exchange to pull data from
               examples: "binance", "bybit", "kucoin", "okx", "mexc", "coinbase"
  - quote      quote currency (the "/USDT" part of "BTC/USDT")
  - timeframe  candle size: "15m", "1h", "4h", "1d", ...
  - strategy   any Strategy instance from alerter.strategies
  - symbols    base assets to watch

Add a new watchlist by appending another Watchlist(...) to the list.
Multiple watchlists run on every scan cycle, in order.
"""

from alerter import (
    PriceBreakout,
    RsiOverbought,
    RsiVolumeSpike,
    Watchlist,
)

# ---- Strategies you can reuse across watchlists ----------------------
strat_oversold = RsiVolumeSpike(
    rsi_length=14,
    rsi_threshold=30,
    vol_length=20,
    vol_multiplier=1.0,   # set 1.5 for "real spike only"
)

# ---- The watchlists themselves ---------------------------------------
WATCHLISTS: list[Watchlist] = [

    # Main: your 58 Binance-listed symbols, 1h candles.
    # (Binance geo-blocks US IPs, so the monitor VM must run in a non-US region.)
    Watchlist(
        name="binance-oversold-1h",
        exchange="binance",
        quote="USDT",
        timeframe="1h",
        strategy=strat_oversold,
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
        name="bybit-longtail-1h",
        exchange="bybit",
        quote="USDT",
        timeframe="1h",
        strategy=strat_oversold,
        symbols=["AIOZ", "AKT", "CRO", "FLR", "GODS", "LMWR", "MEW", "ZKJ"],
    ),

    # ---- Examples (uncomment to enable) ------------------------------

    # # Daily timeframe, tighter threshold, real volume spike only
    # Watchlist(
    #     name="majors-daily-deep-oversold",
    #     exchange="binance",
    #     quote="USDT",
    #     timeframe="1d",
    #     strategy=RsiVolumeSpike(rsi_threshold=25, vol_multiplier=1.5),
    #     symbols=["BTC", "ETH", "SOL", "BNB"],
    # ),

    # # Overbought alerts for taking profit
    # Watchlist(
    #     name="majors-overbought-4h",
    #     exchange="binance",
    #     quote="USDT",
    #     timeframe="4h",
    #     strategy=RsiOverbought(rsi_threshold=75),
    #     symbols=["BTC", "ETH", "SOL"],
    # ),

    # # Breakout alerts on 1d
    # Watchlist(
    #     name="alts-breakout-1d",
    #     exchange="binance",
    #     quote="USDT",
    #     timeframe="1d",
    #     strategy=PriceBreakout(lookback=20),
    #     symbols=["AVAX", "LINK", "ATOM", "DOT"],
    # ),
]

# Note: SCAN_INTERVAL and LOG_LEVEL now live in .env (see .env.example).
