"""
Revolut X client: read-only, signed access to an account's balances and to
market data (pairs + candles), so Revolut X can act as a price source.
alerter/holdings.py turns the balances into watchlists.

Only read endpoints are used, so nothing here can place an order or move money.
Requests are signed as the official docs describe
(developer.revolut.com, "Authenticate requests"): an Ed25519 signature over
``timestamp + METHOD + path + query + body``, base64-encoded.

Setup (done once, by the account owner):
    openssl genpkey -algorithm ed25519 -out private.pem
    openssl pkey -in private.pem -pubout -out public.pem
then paste public.pem into the Revolut X web app -> API keys, and put the API
key and the path to private.pem in the monitor's env file.
"""

from __future__ import annotations

import base64
import time
from decimal import Decimal
from functools import cached_property

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

BASE_URL = "https://revx.revolut.com"
# Signed paths start at /api (per the docs).
BALANCES_PATH = "/api/1.0/balances"
PAIRS_PATH = "/api/1.0/configuration/pairs"
CANDLES_PATH = "/api/1.0/candles/{}"
# ccxt-style timeframe -> Revolut's candle interval in minutes.
_INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240,
                     "1d": 1440, "1w": 10080}
_TIMEOUT_SECONDS = 10

# Balances that aren't coins worth RSI/MACD alerts: fiat and USD/EUR stablecoins.
NOT_COINS = frozenset({
    "USD", "EUR", "GBP", "CHF", "PLN", "RON", "CZK", "HUF", "SEK", "NOK", "DKK",
    "USDT", "USDC", "DAI", "EURC", "PYUSD", "RLUSD", "FDUSD", "TUSD",
})


def sign(private_key: Ed25519PrivateKey, timestamp_ms: str, method: str,
         path: str, query: str = "", body: str = "") -> str:
    """The X-Revx-Signature header value for one request."""
    message = f"{timestamp_ms}{method.upper()}{path}{query}{body}".encode()
    return base64.b64encode(private_key.sign(message)).decode()


class RevolutXClient:
    """Signed, read-only access to Revolut X: balances, plus enough of a
    ccxt-like surface (``markets``, ``rateLimit``, ``fetch_ohlcv``) for the
    Monitor to use it as a price source next to Binance/Bybit."""

    rateLimit = 200   # ms pause between symbols; the candle limits are far higher

    def __init__(self, api_key: str, private_key_pem: bytes):
        if not api_key:
            raise ValueError("Revolut X API key is empty")
        key = load_pem_private_key(private_key_pem, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Revolut X private key must be an Ed25519 key")
        self.api_key = api_key
        self._key = key

    def _get(self, path: str, query: str = ""):
        """Signed GET. `query` is sent exactly as signed (the docs require it)."""
        ts = str(int(time.time() * 1000))
        r = requests.get(
            BASE_URL + path + (f"?{query}" if query else ""),
            headers={
                "X-Revx-API-Key": self.api_key,
                "X-Revx-Timestamp": ts,
                "X-Revx-Signature": sign(self._key, ts, "GET", path, query),
            },
            timeout=_TIMEOUT_SECONDS,
        )
        if r.status_code != 200:
            # Body is a small {"message", "error_id"} JSON — safe to log, no secrets.
            raise RuntimeError(f"Revolut X {path} HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def balances(self) -> list[dict]:
        """Raw GET /balances: a list of {currency, available, reserved, total, ...}."""
        data = self._get(BALANCES_PATH)
        if not isinstance(data, list):
            raise RuntimeError(f"Revolut X balances: unexpected response {data!r:.200}")
        return data

    @cached_property
    def markets(self) -> dict[str, dict]:
        """Active pairs, keyed like ccxt ("BTC/USD"). Loaded once; a failure
        isn't cached, so the next scan simply tries again."""
        pairs = self._get(PAIRS_PATH)
        if not isinstance(pairs, dict):
            raise RuntimeError(f"Revolut X pairs: unexpected response {pairs!r:.200}")
        return {sym: p for sym, p in pairs.items() if p.get("status") == "active"}

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1d",
                    limit: int = 300) -> list[list[float]]:
        """Candles as ccxt-style [start_ms, open, high, low, close, volume] rows,
        oldest first. `symbol` is "BTC/USD"; Revolut's path wants "BTC-USD"."""
        if timeframe not in _INTERVAL_MINUTES:
            raise ValueError(f"Revolut X has no {timeframe!r} candles")
        minutes = _INTERVAL_MINUTES[timeframe]
        since = int(time.time() * 1000) - limit * minutes * 60_000
        data = self._get(CANDLES_PATH.format(symbol.replace("/", "-")),
                         f"interval={minutes}&since={since}")
        rows = [[int(c["start"]), *(float(c[k]) for k in
                 ("open", "high", "low", "close", "volume"))] for c in data["data"]]
        return sorted(rows)


def coin_holdings(entries: list[dict]) -> dict[str, Decimal]:
    """{coin: total amount} for every non-zero, non-fiat, non-stablecoin balance.
    Amounts arrive as strings (to avoid rounding) and stay exact as Decimal."""
    holdings = {}
    for e in entries:
        currency = str(e["currency"]).upper()
        total = Decimal(str(e["total"]))
        if total > 0 and currency not in NOT_COINS:
            holdings[currency] = total
    return holdings
