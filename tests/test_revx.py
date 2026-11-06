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


def test_routes_each_coin_to_first_listing_source(monkeypatch):
    fakes = {"revolutx": FakeExchange({"BTC/USD"}, []),
             "binance": FakeExchange({"BTC/USDT", "ETH/USDT"}, []),
             "bybit": FakeExchange({"CRO/USDT"}, [])}
    monkeypatch.setattr("alerter.revx.get_exchange", fakes.__getitem__)
    held = [{"currency": c, "total": "1"} for c in ("BTC", "ETH", "CRO", "NOPE")]
    wls = holdings_provider(_StubClient(held))()
    assert [(w.exchange, w.quote, w.symbols) for w in wls] == [
        ("revolutx", "USD", ["BTC"]), ("binance", "USDT", ["ETH"]),
        ("bybit", "USDT", ["CRO"])]
    assert wls[0].amounts == {"BTC": Decimal("1")}


class _FakeResponse:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _real_client(monkeypatch, body, calls):
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())

    def fake_get(url, headers, timeout):
        calls.append((url, headers))
        return _FakeResponse(body)
    monkeypatch.setattr("alerter.revx.requests.get", fake_get)
    return RevolutXClient("k" * 64, pem), key


def test_fetch_ohlcv_signs_query_and_parses_docs_example(monkeypatch):
    # Verbatim shape of the docs' CandlesResponseExample (newest first, to check sorting).
    body = {"data": [
        {"start": 1785310133816, "open": "120000.00", "high": "120250.00",
         "low": "119950.00", "close": "120150.00", "volume": "0.18000000"},
        {"start": 1785309833816, "open": "119800.00", "high": "120100.00",
         "low": "119700.00", "close": "120000.00", "volume": "0.25000000"}],
        "metadata": {"timestamp": 1785313433816}}
    calls = []
    client, key = _real_client(monkeypatch, body, calls)
    rows = client.fetch_ohlcv("BTC/USD", "1d", limit=10)
    assert rows == [[1785309833816, 119800.0, 120100.0, 119700.0, 120000.0, 0.25],
                    [1785310133816, 120000.0, 120250.0, 119950.0, 120150.0, 0.18]]
    url, headers = calls[0]
    path, query = url.removeprefix("https://revx.revolut.com").split("?")
    assert path == "/api/1.0/candles/BTC-USD" and query.startswith("interval=1440&since=")
    key.public_key().verify(
        base64.b64decode(headers["X-Revx-Signature"]),
        f"{headers['X-Revx-Timestamp']}GET{path}{query}".encode())


def test_markets_keeps_only_active_pairs(monkeypatch):
    body = {"BTC/USD": {"base": "BTC", "quote": "USD", "status": "active"},
            "OLD/USD": {"base": "OLD", "quote": "USD", "status": "inactive"}}
    client, _ = _real_client(monkeypatch, body, [])
    assert list(client.markets) == ["BTC/USD"]


def test_exchange_load_failure_raises_so_monitor_keeps_old_list(monkeypatch):
    def boom(_id):
        raise RuntimeError("geo-blocked")
    monkeypatch.setattr("alerter.revx.get_exchange", boom)
    try:
        holdings_provider(_StubClient(DOCS_EXAMPLE))()
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")
