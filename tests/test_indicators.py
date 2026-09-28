import math

import pytest

from icarus.indicators import ATR, EMA, RSI, RollingWindow, SessionVWAP, WilderRMA, clamp, squash


def test_rolling_window_evicts_and_tracks_mean():
    window = RollingWindow(3)
    for value in (1.0, 2.0, 3.0, 4.0):
        window.push(value)
    assert window.values == [2.0, 3.0, 4.0]
    assert window.mean == pytest.approx(3.0)
    assert window.max() == 4.0 and window.min() == 2.0
    assert window.ready


def test_rolling_window_percentile_and_zscore():
    window = RollingWindow(5)
    for value in (1.0, 2.0, 3.0, 4.0, 5.0):
        window.push(value)
    assert window.percentile_of(3.0) == pytest.approx(0.6)
    assert window.percentile_of(0.0) == pytest.approx(0.0)
    assert window.percentile_of(9.0) == pytest.approx(1.0)
    assert window.zscore(3.0) == pytest.approx(0.0)


def test_ema_converges_to_a_constant_series():
    ema = EMA(5)
    for _ in range(100):
        ema.update(10.0)
    assert ema.value == pytest.approx(10.0)
    assert ema.ready


def test_wilder_rma_seeds_with_a_simple_average():
    rma = WilderRMA(4)
    for value in (2.0, 4.0, 6.0, 8.0):
        rma.update(value)
    assert rma.value == pytest.approx(5.0)          # SMA seed of the first 4
    rma.update(10.0)                                 # 5 + (10 - 5) / 4
    assert rma.value == pytest.approx(6.25)


def test_atr_matches_hand_computed_true_range():
    atr = ATR(period=2, regime_lookback=10)
    atr.update(10.0, 9.0, 9.5)                       # first bar: TR = 1.0
    atr.update(11.0, 9.8, 10.8)                      # TR = max(1.2, 1.5, 0.3) = 1.5
    assert atr.value == pytest.approx(1.25)
    assert atr.ready


def test_atr_percentile_is_neutral_before_regime_warmup():
    atr = ATR(period=2, regime_lookback=50)
    atr.update(10.0, 9.0, 9.5)
    assert atr.percentile == pytest.approx(0.5)
    assert not atr.regime_ready


def test_rsi_pins_high_on_an_unbroken_advance():
    rsi = RSI(5)
    price = 100.0
    for _ in range(40):
        price *= 1.01
        rsi.update(price)
    assert rsi.value > 95.0


def test_session_vwap_bands_and_reset():
    vwap = SessionVWAP()
    for price in (100.0, 101.0, 99.0, 102.0, 98.0, 100.0):
        vwap.update(price, 1000.0)
    assert vwap.value == pytest.approx(100.0)
    lower, upper = vwap.band(1.0)
    assert lower < vwap.value < upper
    assert vwap.deviation(vwap.value) == pytest.approx(0.0)
    vwap.reset()
    assert vwap.value is None and vwap.band(1.0) is None


def test_session_vwap_falls_back_to_equal_weight_without_volume():
    vwap = SessionVWAP()
    for price in (1.10, 1.20, 1.30):
        vwap.update(price, 0.0)
    assert vwap.value == pytest.approx(1.20)


def test_squash_is_monotone_and_bounded():
    assert squash(-50.0) < squash(0.0) < squash(50.0)
    assert 0.0 <= squash(-50.0) and squash(50.0) <= 1.0
    assert squash(0.0) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        squash(1.0, scale=0.0)


def test_clamp_bounds():
    assert clamp(-1.0) == 0.0 and clamp(2.0) == 1.0 and clamp(0.5) == 0.5
