"""
Revolut X client: reads which coins an account holds, so the monitor can watch
exactly those (instead of a hand-written list in watchlists.py).

Only the balances endpoint is used, so nothing here can place an order or
move money. Requests are signed as the official docs describe
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
import logging
import time
from collections.abc import Callable
from decimal import Decimal

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from .watchlist import Watchlist

log = logging.getLogger("alerter.revx")

BASE_URL = "https://revx.revolut.com"
BALANCES_PATH = "/api/1.0/balances"   # signed path starts at /api (per the docs)
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
    def __init__(self, api_key: str, private_key_pem: bytes):
        if not api_key:
            raise ValueError("Revolut X API key is empty")
        key = load_pem_private_key(private_key_pem, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Revolut X private key must be an Ed25519 key")
        self.api_key = api_key
        self._key = key

    def balances(self) -> list[dict]:
        """Raw GET /balances: a list of {currency, available, reserved, total, ...}."""
        ts = str(int(time.time() * 1000))
        r = requests.get(
            BASE_URL + BALANCES_PATH,
            headers={
                "X-Revx-API-Key": self.api_key,
                "X-Revx-Timestamp": ts,
                "X-Revx-Signature": sign(self._key, ts, "GET", BALANCES_PATH),
            },
            timeout=_TIMEOUT_SECONDS,
        )
        if r.status_code != 200:
            # Body is a small {"message", "error_id"} JSON — safe to log, no secrets.
            raise RuntimeError(f"Revolut X balances HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        if not isinstance(data, list):
            raise RuntimeError(f"Revolut X balances: unexpected response {data!r:.200}")
        return data


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


def holdings_provider(client: RevolutXClient, exchange: str = "binance",
                      quote: str = "USDT") -> Callable[[], list[Watchlist]]:
    """A function the Monitor calls each scan to get a fresh watchlist of the
    coins currently held. Prices still come from `exchange` (Revolut X itself
    isn't a ccxt exchange); held coins not listed there are logged and skipped.
    shortcut: one price exchange only — add a fallback watchlist if many holdings
    turn out to be missing from Binance."""
    def provide() -> list[Watchlist]:
        held = coin_holdings(client.balances())
        log.debug("Revolut X holdings: %s", ", ".join(sorted(held)) or "none")
        return [Watchlist("revolut-x-holdings", exchange, quote,
                          sorted(held), amounts=held)]
    return provide
