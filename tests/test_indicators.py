"""Tests for the raw indicator math."""

import pandas as pd

from alerter.indicators import atr, ema, macd, rsi, sma, stoch_rsi


def test_rsi_all_gains_is_100():
    # A series that only ever rises has no losses, so RSI should pin at 100.
    s = pd.Series([float(i) for i in range(1, 60)])
    assert rsi(s, 14).iloc[-1] == 100.0


def test_rsi_all_losses_is_0():
    s = pd.Series([float(i) for i in range(60, 1, -1)])
    assert rsi(s, 14).iloc[-1] == 0.0


def test_rsi_is_between_0_and_100():
    s = pd.Series([10, 11, 10.5, 12, 11.8, 13, 12.5, 14, 13, 15, 14.2, 16, 15, 17, 16.5, 18])
    val = float(rsi(s, 14).iloc[-1])
    assert 0.0 <= val <= 100.0


def test_rsi_needs_warmup():
    # With fewer than `length` deltas, RSI isn't defined yet -> NaN.
    s = pd.Series([1.0, 2.0, 3.0])
    assert pd.isna(rsi(s, 14).iloc[-1])


def test_sma_is_plain_mean():
    s = pd.Series([2.0, 4.0, 6.0, 8.0])
    assert sma(s, 2).iloc[-1] == 7.0   # mean(6, 8)


def test_macd_signal_is_ema_of_macd_line():
    s = pd.Series([float(i) for i in range(1, 80)])
    macd_line, signal_line, hist = macd(s, 12, 26, 9)
    # signal line is, by definition, the EMA(9) of the macd line
    expected_signal = ema(macd_line, 9)
    assert abs(signal_line.iloc[-1] - expected_signal.iloc[-1]) < 1e-9
    # histogram is macd - signal
    assert abs(hist.iloc[-1] - (macd_line.iloc[-1] - signal_line.iloc[-1])) < 1e-9


def test_macd_bullish_on_rising_series():
    # On a steadily rising series the fast EMA leads the slow one -> macd > signal.
    s = pd.Series([float(i) for i in range(1, 80)])
    macd_line, signal_line, _ = macd(s)
    assert macd_line.iloc[-1] > signal_line.iloc[-1]


def test_stoch_rsi_stays_in_0_100_and_d_lags_k():
    s = pd.Series([10, 11, 10.5, 12, 11.8, 13, 12.5, 14, 13, 15, 14.2, 16, 15, 17] * 4,
                  dtype=float)
    k, d = stoch_rsi(s)
    valid = k.dropna()
    assert ((valid >= 0) & (valid <= 100)).all()
    assert d.first_valid_index() > k.first_valid_index()


def test_atr_of_constant_range_bars_is_that_range():
    close = pd.Series([100.0] * 40)
    assert atr(close + 2, close - 2, close, 14).iloc[-1] == 4.0
