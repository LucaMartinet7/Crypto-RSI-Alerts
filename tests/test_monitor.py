"""Tests for the Monitor orchestration, using a fake exchange + notifier."""

from alerter import Monitor, MonitorConfig, Watchlist, build_detectors
from alerter.notifier import Notifier


class FakeNotifier(Notifier):
    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


class FakeExchange:
    """Stands in for a ccxt exchange: knows one market and returns a fixed
    candle series with no network and no rate-limit delay."""

    rateLimit = 0  # -> time.sleep(0)

    def __init__(self, listed: set[str], closes: list[float]):
        self.markets = {sym: {} for sym in listed}
        self._closes = closes

    def fetch_ohlcv(self, symbol, timeframe="1d", limit=300):
        # [ts, open, high, low, close, volume] per bar
        return [[i, c, c, c, c, 100.0] for i, c in enumerate(self._closes)]


def _monitor(monkeypatch, tmp_path, closes, listed=("BTC/USDT",), **cfg_kw):
    ex = FakeExchange(set(listed), closes)
    monkeypatch.setattr("alerter.monitor.get_exchange", lambda _id: ex)
    cfg = MonitorConfig(**cfg_kw)
    notifier = FakeNotifier()
    wl = Watchlist("t", "binance", "USDT", [s.split("/")[0] for s in listed])
    mon = Monitor([wl], notifier, build_detectors(cfg),
                  timeframe=cfg.timeframe, digest_hour_utc=cfg.digest_hour_utc,
                  state_path=str(tmp_path / "state.json"))
    return mon, notifier


def test_first_scan_is_silent_but_records_state(monkeypatch, tmp_path):
    rising = [float(i) for i in range(1, 61)]
    mon, notifier = _monitor(monkeypatch, tmp_path, rising)
    mon.scan_once()
    assert notifier.sent == []                       # nothing on first sighting
    # state was persisted with the symbol recorded
    raw = mon.store.load()
    assert "binance:BTC/USDT" in raw["zone"]
    assert "binance:BTC/USDT" in raw["macd_side"]


def test_skips_unlisted_symbol(monkeypatch, tmp_path):
    rising = [float(i) for i in range(1, 61)]
    # watchlist asks for BTC + DOGE, exchange only lists BTC
    ex = FakeExchange({"BTC/USDT"}, rising)
    monkeypatch.setattr("alerter.monitor.get_exchange", lambda _id: ex)
    notifier = FakeNotifier()
    wl = Watchlist("t", "binance", "USDT", ["BTC", "DOGE"])
    mon = Monitor([wl], notifier, build_detectors(MonitorConfig()),
                  state_path=str(tmp_path / "s.json"))
    mon.scan_once()
    raw = mon.store.load()
    assert "binance:DOGE/USDT" not in raw["zone"]     # unlisted -> never recorded


def test_digest_sends_once_per_day(monkeypatch, tmp_path):
    rising = [float(i) for i in range(1, 61)]
    mon, notifier = _monitor(monkeypatch, tmp_path, rising, digest_hour_utc=0)
    mon.scan_once()
    before = len(notifier.sent)
    mon.maybe_send_digest()
    assert any("Daily digest" in m for m in notifier.sent)
    after_first = len(notifier.sent)
    assert after_first == before + 1
    mon.maybe_send_digest()                           # already sent today
    assert len(notifier.sent) == after_first          # no duplicate


def test_prune_removes_stale_state(monkeypatch, tmp_path):
    rising = [float(i) for i in range(1, 61)]
    mon, _ = _monitor(monkeypatch, tmp_path, rising)
    # inject a stale symbol that's not in any watchlist
    mon.detectors[0].zone["binance:OLD/USDT"] = "neutral"
    mon.scan_once()
    raw = mon.store.load()
    assert "binance:OLD/USDT" not in raw["zone"]
