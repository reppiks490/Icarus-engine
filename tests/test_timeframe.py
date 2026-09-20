import pytest

from icarus.config import AssetClass, profile_for
from icarus.data import synthetic_for
from icarus.timeframe import at_timeframe, htf_bars, parse_timeframe, resample, scale_bars

BARS = synthetic_for(AssetClass.FUTURES, 1200, seed=3)      # 5m source


@pytest.mark.parametrize("label,minutes", [("5m", 5), ("10m", 10), ("1h", 60), ("4h", 240), (7, 7), ("90m", 90)])
def test_parse_timeframe(label, minutes):
    assert parse_timeframe(label) == minutes


def test_parse_timeframe_rejects_nonsense():
    with pytest.raises(ValueError):
        parse_timeframe("fortnight")
    with pytest.raises(ValueError):
        parse_timeframe(0)


def test_scale_bars_preserves_duration():
    assert scale_bars(24, 10, 5) == 48          # 4 hours stays 4 hours
    assert scale_bars(24, 10, 30) == 8
    assert scale_bars(1, 10, 60) == 1           # never rounds to zero


def test_resample_conserves_volume_and_span():
    coarse = resample(BARS, "30m")
    assert len(coarse) == pytest.approx(len(BARS) / 6, abs=2)
    assert sum(b.volume for b in coarse) == pytest.approx(sum(b.volume for b in BARS))
    assert coarse[-1].close == pytest.approx(BARS[-1].close)


def test_resample_produces_valid_bars_on_a_clock_grid():
    for bar in resample(BARS, "1h"):
        assert bar.low <= bar.open <= bar.high
        assert bar.low <= bar.close <= bar.high
        assert bar.ts.minute == 0


def test_resample_to_the_same_timeframe_is_a_no_op():
    same = resample(BARS, "5m")
    assert len(same) == len(BARS)
    assert [b.close for b in same] == [b.close for b in BARS]


def test_resample_aggregates_extremes_not_just_endpoints():
    coarse = resample(BARS, "30m")
    assert coarse[0].high == max(b.high for b in BARS[:6])
    assert coarse[0].low == min(b.low for b in BARS[:6])


def test_resample_of_nothing_is_nothing():
    assert resample([], "10m") == []


def test_profile_rescaling_preserves_wall_clock_duration():
    profile = profile_for(AssetClass.MICRO_FUTURES)        # calibrated on 10m
    assert profile.base_timeframe_min == 10
    faster = at_timeframe(profile, "2m")
    assert faster.base_timeframe_min == 2
    assert faster.time_stop_bars == profile.time_stop_bars * 5
    assert faster.cooldown_bars_after_exit == profile.cooldown_bars_after_exit * 5
    # Shape parameters are scale-free and must NOT be rescaled.
    assert faster.swing_strength == profile.swing_strength
    assert faster.sweep_reclaim_bars == profile.sweep_reclaim_bars
    assert faster.risk_per_trade == profile.risk_per_trade


def test_rescaling_to_the_same_timeframe_returns_the_same_profile():
    profile = profile_for(AssetClass.MICRO_FUTURES)
    assert at_timeframe(profile, "10m") is profile


def test_htf_bars():
    assert htf_bars("10m", "4h") == 24
    assert htf_bars("2m", "4h") == 120
    with pytest.raises(ValueError):
        htf_bars("1h", "10m")
