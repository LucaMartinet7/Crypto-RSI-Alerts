"""Tests for the Revolut X client and the holdings-driven watchlist (no network)."""

import base64
from decimal import Decimal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from alerter import Alert, Monitor, Watchlist
from alerter.revx import RevolutXClient, coin_holdings, holdings_provider, sign
from tests.test_monitor import FakeExchange, FakeNotifier

# Verbatim example response from the official GET /1.0/balances docs.
DOCS_EXAMPLE = [
    {"currency": "BTC", "available": "1.25000000", "reserved": "0.10000000",
     "total": "1.35000000"},
    {"currency": "ETH", "available": "10.00000000", "reserved": "0.00000000",
     "staked": "32.00000000", "total": "42.00000000"},
    {"currency": "USD", "available": "5400.50", "reserved": "100.00", "total": "5500.50"},
]


def test_signature_matches_documented_message_format():
    key = Ed25519PrivateKey.generate()
    sig = sign(key, "1785313433816", "get", "/api/1.0/orders/active", "limit=10")
    # Documented message: timestamp + METHOD + path + query + body, no separators.
    key.public_key().verify(base64.b64decode(sig),
                            b"1785313433816GET/api/1.0/orders/activelimit=10")


def test_client_rejects_non_ed25519_or_missing_key():
    pem = Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    assert RevolutXClient("k" * 64, pem).api_key == "k" * 64
    for args in (("", pem), ("k", b"not a pem")):
        try:
            RevolutXClient(*args)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {args!r:.40}")


def test_coin_holdings_drops_fiat_and_zero_balances():
    entries = [*DOCS_EXAMPLE, {"currency": "SOL", "available": "0", "reserved": "0",
                               "total": "0"}]
    assert coin_holdings(entries) == {"BTC": Decimal("1.35"), "ETH": Decimal("42")}


class _StubClient:
    def __init__(self, entries):
        self.entries = entries

    def balances(self):
        if isinstance(self.entries, Exception):
            raise self.entries
        return self.entries


def _holdings_monitor(monkeypatch, tmp_path, client):
    ex = FakeExchange({"BTC/USDT", "ETH/USDT"}, [float(i) for i in range(1, 61)])
    monkeypatch.setattr("alerter.monitor.get_exchange", lambda _id: ex)
    monkeypatch.setattr("alerter.revx.get_exchange", lambda _id: ex)
    from alerter import MonitorConfig, build_detectors
    notifier = FakeNotifier()
    mon = Monitor([], notifier, build_detectors(MonitorConfig()),
                  state_path=str(tmp_path / "s.json"),
                  watchlist_provider=holdings_provider(client))
    return mon, notifier


def test_scan_watches_held_coins(monkeypatch, tmp_path):
    mon, _ = _holdings_monitor(monkeypatch, tmp_path, _StubClient(DOCS_EXAMPLE))
    mon.scan_once()
    assert set(mon.store.load()["zone"]) == {"binance:BTC/USDT", "binance:ETH/USDT"}


def test_failed_refresh_keeps_previous_holdings_and_state(monkeypatch, tmp_path):
    client = _StubClient(DOCS_EXAMPLE)
    mon, _ = _holdings_monitor(monkeypatch, tmp_path, client)
    mon.scan_once()
    client.entries = RuntimeError("HTTP 503")
    mon.scan_once()
    assert mon.watchlists[0].symbols == ["BTC", "ETH"]
    assert set(mon.store.load()["zone"]) == {"binance:BTC/USDT", "binance:ETH/USDT"}


def test_failed_first_refresh_skips_scan_without_wiping_state(monkeypatch, tmp_path):
    (tmp_path / "s.json").write_text('{"zone": {"binance:BTC/USDT": "neutral"}}')
    mon, _ = _holdings_monitor(monkeypatch, tmp_path, _StubClient(RuntimeError("down")))
    mon.scan_once()
    assert mon.store.load()["zone"] == {"binance:BTC/USDT": "neutral"}


def test_alert_mentions_amount_held(tmp_path):
    notifier = FakeNotifier()
    from alerter import MonitorConfig, build_detectors
    mon = Monitor([], notifier, build_detectors(MonitorConfig()),
                  state_path=str(tmp_path / "s.json"))
    wl = Watchlist("h", "binance", "USDT", ["SOL"], amounts={"SOL": Decimal("12.400")})
    mon._send_alert("SOL", wl, Alert("🔻", "crossed under RSI 30", "RSI 28"))
    assert "You hold 12.4 SOL" in notifier.sent[0]


def test_routes_each_coin_to_first_listing_exchange(monkeypatch):
    fakes = {"binance": FakeExchange({"BTC/USDT", "ETH/USDT"}, []),
             "bybit": FakeExchange({"BTC/USDT", "CRO/USDT"}, [])}
    monkeypatch.setattr("alerter.revx.get_exchange", fakes.__getitem__)
    held = [{"currency": "BTC", "total": "1"}, {"currency": "CRO", "total": "5"},
            {"currency": "NOPE", "total": "2"}]
    wls = holdings_provider(_StubClient(held), extra_coins=["ETH"])()
    assert [(w.exchange, w.symbols) for w in wls] == [
        ("binance", ["BTC", "ETH"]), ("bybit", ["CRO"])]
    assert wls[0].amounts == {"BTC": Decimal("1")}      # ETH is watched, not held


def test_exchange_load_failure_raises_so_monitor_keeps_old_list(monkeypatch):
    def boom(_id):
        raise RuntimeError("geo-blocked")
    monkeypatch.setattr("alerter.revx.get_exchange", boom)
    try:
        holdings_provider(_StubClient(DOCS_EXAMPLE))()
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")
