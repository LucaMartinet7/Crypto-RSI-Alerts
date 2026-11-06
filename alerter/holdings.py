"""
Holdings -> watchlists: watch exactly the coins an account holds, each priced
on the first source that lists it (Revolut X, then Binance, then Bybit).
The Monitor calls the provider below at the start of every scan.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Protocol

from .exchanges import get_exchange
from .revx import coin_holdings
from .watchlist import Watchlist

log = logging.getLogger("alerter.holdings")


class BalanceSource(Protocol):
    def balances(self) -> list[dict]: ...


# Where prices come from, in order: each held coin is priced on the first source
# that lists it. Revolut X first, so alerts match what he actually trades at.
PRICE_SOURCES: tuple[tuple[str, str], ...] = (
    ("revolutx", "USD"), ("binance", "USDT"), ("bybit", "USDT"),
)


def holdings_provider(client: BalanceSource,
                      sources: Sequence[tuple[str, str]] = PRICE_SOURCES,
                      ) -> Callable[[], list[Watchlist]]:
    """A function the Monitor calls each scan for fresh watchlists of every
    coin currently held (see route_by_listing for where prices come from)."""
    def provide() -> list[Watchlist]:
        held = coin_holdings(client.balances())
        return route_by_listing(sorted(held), held, sources)
    return provide


def route_by_listing(coins: list[str], amounts: dict[str, Decimal],
                     sources: Sequence[tuple[str, str]]) -> list[Watchlist]:
    """One watchlist per (exchange, quote): each coin goes to the FIRST source
    that lists it, so no coin is scanned (or alerted) twice. Raises if a source
    can't load, so the Monitor keeps its previous watchlists rather than
    silently moving coins elsewhere (which would reset their saved state)."""
    remaining, out = list(coins), []
    for ex_id, quote in sources:
        markets = get_exchange(ex_id).markets or {}
        here = [c for c in remaining if f"{c}/{quote}" in markets]
        remaining = [c for c in remaining if c not in here]
        if here:
            out.append(Watchlist(f"holdings-{ex_id}", ex_id, quote, here,
                                 amounts={c: amounts[c] for c in here if c in amounts}))
    if remaining:
        log.info("not listed on %s, not watched: %s",
                 "/".join(ex for ex, _ in sources), ", ".join(remaining))
    return out
