"""Tests for the JSON state store."""

from alerter.state import JsonStateStore


def test_round_trip(tmp_path):
    store = JsonStateStore(tmp_path / "state.json")
    data = {"zone": {"binance:BTC/USDT": "oversold"}, "last_digest_date": "2026-06-01"}
    store.save(data)
    assert store.load() == data


def test_missing_file_returns_empty(tmp_path):
    store = JsonStateStore(tmp_path / "does_not_exist.json")
    assert store.load() == {}


def test_corrupt_file_returns_empty_not_crash(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ this is not valid json ]")
    store = JsonStateStore(path)
    assert store.load() == {}   # degrades gracefully instead of raising


def test_write_is_atomic_no_temp_left_behind(tmp_path):
    path = tmp_path / "state.json"
    store = JsonStateStore(path)
    store.save({"a": 1})
    # the temp file used during the atomic rename must not linger
    assert not (tmp_path / "state.json.tmp").exists()
    assert path.exists()
