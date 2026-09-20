import pytest

from icarus.data import synthetic_for
from icarus.filters import AdaptiveKalman, FractalDimensionIndex
from icarus.indicators import ATR


def test_fdi_starts_at_the_random_walk_prior():
    fdi = FractalDimensionIndex(30, 5)
    assert fdi.value == pytest.approx(1.5)
    assert not fdi.ready


def test_fdi_rejects_a_degenerate_length():
    with pytest.raises(ValueError):
        FractalDimensionIndex(length=2)


def test_fdi_is_bounded_and_ranks_trend_below_chop():
    trend = FractalDimensionIndex(20, 3)
    chop = FractalDimensionIndex(20, 3)
    for index in range(120):
        price = 100.0 + index                       # a clean monotone ramp
        trend.update(price + 0.2, price - 0.2)
        wobble = 100.0 + (2.0 if index % 2 else -2.0)   # pure alternation
        chop.update(wobble + 0.2, wobble - 0.2)
    assert 1.0 <= trend.value <= 2.0 and 1.0 <= chop.value <= 2.0
    assert trend.value < chop.value
    assert 0.0 <= trend.choppiness <= 1.0


def test_kalman_seeds_on_the_first_measurement():
    kalman = AdaptiveKalman()
    state = kalman.update(100.0, atr=1.0, choppiness=0.5)
    assert state.estimate == pytest.approx(100.0)
    assert kalman.ready


def test_kalman_lags_price_instead_of_chasing_it():
    """The whole point: the trail anchor must not track a single-bar spike."""
    kalman = AdaptiveKalman()
    for _ in range(50):
        kalman.update(100.0, atr=1.0, choppiness=0.3)
    before = kalman.estimate
    kalman.update(120.0, atr=1.0, choppiness=0.3)      # a 20-ATR spike
    moved = kalman.estimate - before
    assert 0.0 < moved < 5.0, "filter chased the spike"


def test_kalman_is_slower_in_chop_than_in_trend():
    trendy, choppy = AdaptiveKalman(), AdaptiveKalman()
    for _ in range(60):
        trendy.update(100.0, 1.0, 0.0)
        choppy.update(100.0, 1.0, 1.0)
    trendy.update(105.0, 1.0, 0.0)
    choppy.update(105.0, 1.0, 1.0)
    assert trendy.estimate > choppy.estimate, "chop should damp the filter more"


def test_kalman_survives_a_zero_atr():
    kalman = AdaptiveKalman()
    kalman.update(100.0, atr=0.0, choppiness=0.5)
    state = kalman.update(101.0, atr=0.0, choppiness=0.5)
    assert state.estimate == pytest.approx(state.estimate)     # no NaN, no crash


def test_filters_track_a_real_tape_without_drifting_away():
    atr, fdi, kalman = ATR(25, 240), FractalDimensionIndex(30, 5), AdaptiveKalman()
    bars = synthetic_for("micro_futures", 1200, seed=11)
    for bar in bars:
        value = atr.update(bar.high, bar.low, bar.close)
        fdi.update(bar.high, bar.low)
        kalman.update(bar.close, value, fdi.choppiness)
    assert abs(bars[-1].close - kalman.estimate) < 8.0 * atr.value
    assert 1.0 <= fdi.value <= 2.0
