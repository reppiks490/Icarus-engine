from datetime import datetime, timedelta, timezone

import pytest

from icarus.data import Bar
from icarus.features.liquidity import LiquidityMap, PoolKind
from icarus.features.structure import Swing, SwingType

START = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)
ATR = 1.0


def bar(index, open_, high, low, close, volume=100.0):
    return Bar(ts=START + timedelta(minutes=5 * index), open=open_, high=high,
               low=low, close=close, volume=volume)


def seeded_map(level, kind):
    """A map holding one pool at ``level``, already eligible to be raided."""
    liquidity = LiquidityMap(min_penetration_atr=0.05, max_penetration_atr=1.30, reclaim_bars=3)
    liquidity.update(bar(0, 100.0, 100.5, 99.5, 100.0), ATR)
    swing_kind = SwingType.HIGH if kind is PoolKind.SWING_HIGH else SwingType.LOW
    liquidity.ingest_swings([Swing(ts=START, price=level, kind=swing_kind, index=0)])
    return liquidity


def test_raid_above_a_swing_high_that_reclaims_is_a_short_sweep():
    liquidity = seeded_map(101.0, PoolKind.SWING_HIGH)
    # Trades 0.4 ATR through the pool and closes back underneath it, same bar.
    sweep = liquidity.update(bar(1, 100.4, 101.4, 100.2, 100.6), ATR)
    assert sweep is not None
    assert sweep.reclaim_bars == 0
    assert sweep.direction == -1
    assert sweep.pool.kind is PoolKind.SWING_HIGH
    assert sweep.extreme == pytest.approx(101.4)
    assert sweep.penetration_atr == pytest.approx(0.4)
    assert 0.0 <= sweep.quality <= 1.0


def test_raid_below_a_swing_low_that_reclaims_is_a_long_sweep():
    liquidity = seeded_map(99.0, PoolKind.SWING_LOW)
    sweep = liquidity.update(bar(1, 99.6, 99.8, 98.6, 99.4), ATR)
    assert sweep is not None
    assert sweep.direction == 1
    assert sweep.extreme == pytest.approx(98.6)


def test_acceptance_beyond_the_level_is_a_break_not_a_sweep():
    liquidity = seeded_map(101.0, PoolKind.SWING_HIGH)
    # Pokes through and keeps closing above for longer than the reclaim window.
    assert liquidity.update(bar(1, 100.8, 101.4, 100.7, 101.3), ATR) is None
    for index in range(2, 6):
        assert liquidity.update(bar(index, 101.3, 101.5, 101.2, 101.4), ATR) is None


def test_penetration_beyond_the_ceiling_retires_the_pool():
    liquidity = seeded_map(101.0, PoolKind.SWING_HIGH)
    # 2.0 ATR through the level is a breakout: no sweep, and the pool is consumed.
    assert liquidity.update(bar(1, 100.9, 103.0, 100.4, 100.5), ATR) is None
    assert PoolKind.SWING_HIGH not in {pool.kind for pool in liquidity.pools()}


def test_shallow_penetration_is_ignored_as_noise():
    liquidity = seeded_map(101.0, PoolKind.SWING_HIGH)
    # Only 0.02 ATR through -- inside the noise floor.
    assert liquidity.update(bar(1, 100.8, 101.02, 100.7, 100.7), ATR) is None


def test_repeated_levels_cluster_into_equal_highs_with_more_weight():
    liquidity = LiquidityMap()
    liquidity.update(bar(0, 100.0, 100.5, 99.5, 100.0), ATR)
    swing = Swing(ts=START, price=101.0, kind=SwingType.HIGH, index=0)
    liquidity.ingest_swings([swing])
    single = next(p for p in liquidity.pools() if p.kind is PoolKind.SWING_HIGH).weight
    liquidity.ingest_swings([swing])
    kinds = {pool.kind for pool in liquidity.pools()}
    assert PoolKind.EQUAL_HIGHS in kinds
    assert next(p for p in liquidity.pools() if p.kind is PoolKind.SWING_HIGH).weight > single


def test_session_roll_promotes_yesterdays_extremes():
    liquidity = LiquidityMap()
    liquidity.update(bar(0, 100.0, 103.0, 97.0, 100.0), ATR)
    liquidity.roll_session(bar(1, 100.0, 100.5, 99.5, 100.0))
    kinds = {pool.kind for pool in liquidity.pools()}
    assert PoolKind.PRIOR_SESSION_HIGH in kinds and PoolKind.PRIOR_SESSION_LOW in kinds
    assert liquidity.prior_session_high == pytest.approx(103.0)
    assert liquidity.prior_session_low == pytest.approx(97.0)


def test_nearest_pool_picks_the_closest_level_on_the_requested_side():
    liquidity = seeded_map(101.0, PoolKind.SWING_HIGH)
    above = liquidity.nearest_pool(100.0, side=1)
    assert above is not None and above.level >= 100.0
    assert liquidity.nearest_pool(100.0, side=-1).level <= 100.0


def test_tolerance_is_per_instance():
    first, second = LiquidityMap(), LiquidityMap()
    first.update(bar(0, 100.0, 100.5, 99.5, 100.0), ATR)
    assert second._tolerance == 0.0
