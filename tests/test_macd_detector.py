"""Tests for the MACD crossover detector's state machine."""

import pandas as pd

from alerter.signals.macd import BEAR, BULL, MacdCrossDetector

KEY = "binance:BTC/USDT"
RISING = pd.Series([float(i) for i in range(1, 80)])        # -> bullish
FALLING = pd.Series([float(i) for i in range(80, 1, -1)])   # -> bearish


def test_first_sighting_is_silent():
    det = MacdCrossDetector()
    assert det.update(KEY, RISING) == []
    assert det.side[KEY] == BULL


def test_no_alert_when_side_unchanged():
    det = MacdCrossDetector()
    det.side[KEY] = BULL
    assert det.update(KEY, RISING) == []


def test_bearish_cross_alerts():
    det = MacdCrossDetector()
    det.side[KEY] = BULL
    alerts = det.update(KEY, FALLING)
    assert len(alerts) == 1
    assert alerts[0].emoji == "🟥"
    assert det.side[KEY] == BEAR


def test_bullish_cross_alerts():
    det = MacdCrossDetector()
    det.side[KEY] = BEAR
    alerts = det.update(KEY, RISING)
    assert len(alerts) == 1
    assert alerts[0].emoji == "🟩"
    assert det.side[KEY] == BULL


def test_state_round_trip_and_prune():
    det = MacdCrossDetector()
    det.side = {KEY: BULL, "binance:GONE/USDT": BEAR}
    restored = MacdCrossDetector()
    restored.load_state(det.state_dict())
    assert restored.side == {KEY: BULL, "binance:GONE/USDT": BEAR}
    restored.prune({KEY})
    assert restored.side == {KEY: BULL}
