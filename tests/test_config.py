"""Tests for MonitorConfig env parsing."""

from alerter.config import MonitorConfig


def test_defaults_when_env_empty():
    cfg = MonitorConfig.from_env({})
    assert cfg.rsi_length == 14
    assert cfg.oversold_threshold == 30.0
    assert cfg.overbought_threshold == 70.0
    assert cfg.macd_fast == 12 and cfg.macd_slow == 26 and cfg.macd_signal == 9
    assert cfg.timeframe == "1d"
    assert cfg.digest_hour_utc == 8
    assert cfg.interval_seconds == 600


def test_reads_overrides_from_env():
    cfg = MonitorConfig.from_env({
        "RSI_THRESHOLD": "25",
        "RSI_HIGH_THRESHOLD": "75",
        "MONITOR_TIMEFRAME": "4h",
        "MONITOR_INTERVAL": "300",
        "MACD_FAST": "8",
    })
    assert cfg.oversold_threshold == 25.0
    assert cfg.overbought_threshold == 75.0
    assert cfg.timeframe == "4h"
    assert cfg.interval_seconds == 300
    assert cfg.macd_fast == 8


def test_is_immutable():
    cfg = MonitorConfig()
    try:
        cfg.rsi_length = 99  # type: ignore[misc]
    except Exception as e:
        assert "frozen" in str(e).lower() or isinstance(e, AttributeError)
    else:
        raise AssertionError("MonitorConfig should be frozen/immutable")
