"""Tests for the BTC buy-the-dip detector."""

import numpy as np
import pandas as pd

from alerter.signals import dip
from alerter.signals.dip import BuyTheDipDetector, dip_conditions

DAY_MS = 86_400_000
KEY = "revolutx:BTC/USD"


def _candles(n=520, seed=1):
    rng = np.random.default_rng(seed)
    close = 30_000 * np.exp(np.cumsum(rng.normal(0.001, 0.03, n)))
    return pd.DataFrame({
        "ts": np.arange(n) * DAY_MS + 1_700_006_400_000,     # a Monday 00:00 UTC
        "open": close, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": rng.uniform(100, 200, n)})


def test_conditions_returns_five_bools_on_real_shaped_data():
    out = dip_conditions(_candles())
    assert list(out) == ["weekly trend", "stoch RSI cross", "MACD improving",
                         "volume", "near support"]
    assert all(isinstance(v, bool) for v in out.values())


def test_short_history_is_never_a_signal():
    assert dip_conditions(_candles(n=60))["weekly trend"] is False   # no 50-week SMA yet


def test_alerts_once_per_closed_candle_and_ignores_live_one(monkeypatch):
    seen = []
    monkeypatch.setattr(dip, "dip_conditions",
                        lambda c: seen.append(len(c)) or dict.fromkeys("abcde", True))
    det, candles = BuyTheDipDetector(), _candles()
    assert len(det.update(KEY, candles)) == 1
    assert seen == [len(candles) - 1]                         # live candle dropped
    assert det.update(KEY, candles) == []                     # same candle: no repeat
    nxt = pd.concat([candles, candles.tail(1).assign(ts=candles.ts.iloc[-1] + DAY_MS)])
    assert len(det.update(KEY, nxt.reset_index(drop=True))) == 1   # next day may fire


def test_only_watches_btc_and_needs_all_five(monkeypatch):
    det = BuyTheDipDetector()
    monkeypatch.setattr(dip, "dip_conditions", lambda c: dict.fromkeys("abcde", True))
    assert det.update("revolutx:ETH/USD", _candles()) == []
    monkeypatch.setattr(dip, "dip_conditions",
                        lambda c: {**dict.fromkeys("abcd", True), "e": False})
    assert det.update(KEY, _candles()) == []


def test_state_round_trip_and_prune():
    det = BuyTheDipDetector()
    det.load_state({"dip_last_signal": {KEY: 123, "binance:OLD/USDT": 1}})
    det.prune({KEY})
    assert det.state_dict() == {"dip_last_signal": {KEY: 123}}
