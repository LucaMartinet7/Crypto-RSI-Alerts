"""Tests for the RSI zone detector's state machine."""

import pandas as pd

from alerter.signals.rsi import NEUTRAL, OVERBOUGHT, OVERSOLD, RsiZoneDetector

KEY = "binance:BTC/USDT"


def _series_for_rsi(target: str) -> pd.Series:
    """A close series whose final RSI lands in the requested zone."""
    if target == OVERSOLD:
        return pd.Series([100.0] * 20 + [100.0 - i * 3 for i in range(1, 30)])
    if target == OVERBOUGHT:
        return pd.Series([10.0] * 20 + [10.0 + i * 3 for i in range(1, 30)])
    # neutral: gentle chop
    base = [50.0]
    for i in range(40):
        base.append(base[-1] + (1.0 if i % 2 == 0 else -0.9))
    return pd.Series(base)


def test_first_sighting_is_silent():
    det = RsiZoneDetector()
    alerts = det.update(KEY, _series_for_rsi(OVERSOLD))
    assert alerts == []                      # no alert on first observation
    assert det.zone[KEY] == OVERSOLD         # but the zone is recorded


def test_no_alert_when_zone_unchanged():
    det = RsiZoneDetector()
    det.zone[KEY] = OVERSOLD
    assert det.update(KEY, _series_for_rsi(OVERSOLD)) == []


def test_crossing_into_oversold_alerts():
    det = RsiZoneDetector()
    det.zone[KEY] = NEUTRAL
    alerts = det.update(KEY, _series_for_rsi(OVERSOLD))
    assert len(alerts) == 1
    assert alerts[0].emoji == "🔻"
    assert det.zone[KEY] == OVERSOLD


def test_recovery_records_for_digest():
    det = RsiZoneDetector()
    det.zone[KEY] = OVERSOLD
    alerts = det.update(KEY, _series_for_rsi(NEUTRAL))
    assert len(alerts) == 1
    assert alerts[0].emoji == "🟢"
    assert KEY in det.recovered_today


def test_overbought_and_cooloff():
    det = RsiZoneDetector()
    det.zone[KEY] = NEUTRAL
    assert det.update(KEY, _series_for_rsi(OVERBOUGHT))[0].emoji == "📈"
    cooled = det.update(KEY, _series_for_rsi(NEUTRAL))
    assert cooled[0].emoji == "🔵"
    assert KEY in det.cooled_today


def test_state_round_trip():
    det = RsiZoneDetector()
    det.zone = {KEY: OVERBOUGHT}
    det.recovered_today = {"binance:ETH/USDT"}
    restored = RsiZoneDetector()
    restored.load_state(det.state_dict())
    assert restored.zone == {KEY: OVERBOUGHT}
    assert restored.recovered_today == {"binance:ETH/USDT"}


def test_digest_has_four_sections():
    det = RsiZoneDetector()
    det.zone = {KEY: OVERSOLD}
    sections = det.digest_sections()
    assert len(sections) == 4
    assert sections[0].keys == [KEY]         # "currently oversold"


def test_prune_drops_removed_symbols():
    det = RsiZoneDetector()
    det.zone = {KEY: OVERSOLD, "binance:GONE/USDT": NEUTRAL}
    det.cooled_today = {"binance:GONE/USDT"}
    det.prune({KEY})
    assert det.zone == {KEY: OVERSOLD}
    assert det.cooled_today == set()
