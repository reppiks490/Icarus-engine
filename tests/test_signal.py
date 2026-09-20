from datetime import datetime, timezone

import pytest

from icarus.config import AssetClass, profile_for
from icarus.features.liquidity import LiquidityMap, LiquidityPool, PoolKind, Sweep
from icarus.features.orderflow import OrderFlowState
from icarus.features.sentiment import SentimentOverlay
from icarus.features.structure import MarketStructure
from icarus.features.volatility import VolatilityState
from icarus.indicators import SessionVWAP
from icarus.signal import ConfluenceEngine

NOW = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
PROFILE = profile_for(AssetClass.FUTURES)


def make_sweep(direction=1, quality=0.9):
    pool = LiquidityPool(level=100.0, kind=PoolKind.PRIOR_SESSION_LOW, created_index=0)
    return Sweep(ts=NOW, index=10, direction=direction, pool=pool, extreme=99.0,
                 penetration_atr=0.4, reclaim_bars=0, rejection=0.7, quality=quality)


def strong_flow(direction=1):
    return OrderFlowState(delta=500.0, cvd=5000.0, cvd_slope=direction * 0.9,
                          delta_z=direction * 2.5, absorption=0.8,
                          divergence=float(direction), is_proxy=False)


def good_regime():
    return VolatilityState(atr=1.0, percentile=0.55, expansion=1.25, squeeze=0.8,
                           shock=1.1, tradable=True)


def liquidity_with_room(distance=4.0):
    liquidity = LiquidityMap()
    liquidity._pools.append(LiquidityPool(level=100.0 + distance, kind=PoolKind.SWING_HIGH,
                                          created_index=0))
    liquidity._pools.append(LiquidityPool(level=100.0 - distance, kind=PoolKind.SWING_LOW,
                                          created_index=0))
    return liquidity


def evaluate(engine=None, **overrides):
    engine = engine or ConfluenceEngine(PROFILE.weights, min_score=0.50)
    kwargs = dict(
        ts=NOW, price=100.0, sweep=make_sweep(), volatility=good_regime(),
        order_flow=strong_flow(), structure=MarketStructure(), liquidity=liquidity_with_room(),
        vwap=SessionVWAP(), sentiment=SentimentOverlay(), rsi=45.0, session_open=True,
    )
    kwargs.update(overrides)
    return engine.evaluate(**kwargs)


def test_closed_session_is_a_hard_veto():
    signal = evaluate(session_open=False)
    assert not signal.actionable and signal.veto == "session-closed"


def test_untradable_regime_is_a_hard_veto():
    signal = evaluate(volatility=VolatilityState(1.0, 0.02, 1.0, 1.0, 0.5, False, "dead-tape"))
    assert not signal.actionable and signal.veto.startswith("regime:")


def test_no_sweep_means_no_trade():
    signal = evaluate(sweep=None)
    assert not signal.actionable and signal.veto == "no-trigger"
    assert signal.direction == 0


def test_insufficient_room_to_the_next_pool_is_vetoed():
    signal = evaluate(liquidity=liquidity_with_room(distance=0.5))
    assert not signal.actionable and signal.veto.startswith("no-room")


def test_score_below_threshold_is_reported_not_traded():
    engine = ConfluenceEngine(PROFILE.weights, min_score=0.99)
    signal = evaluate(engine=engine)
    assert not signal.actionable
    assert signal.veto.startswith("below-threshold")
    assert 0.0 < signal.score < 0.99           # the score is still published for audit


def test_confluence_produces_a_trade_when_every_layer_agrees():
    signal = evaluate()
    assert signal.actionable
    assert signal.direction == 1
    assert signal.stop_anchor == pytest.approx(99.0)
    assert set(signal.components) == set(PROFILE.weights.as_dict())
    assert all(0.0 <= value <= 1.0 for value in signal.components.values())


def test_direction_always_comes_from_the_sweep_never_from_an_overlay():
    bearish = SentimentOverlay()
    from icarus.features.sentiment import SentimentReading
    bearish.push(SentimentReading(value=-1.0, ts=NOW))
    signal = evaluate(sweep=make_sweep(direction=1), sentiment=bearish)
    # Sentiment may drain the score to a veto, but it can never produce a short.
    assert signal.direction in (0, 1)


def test_score_is_bounded_and_normalised():
    signal = evaluate()
    assert 0.0 <= signal.score <= 1.0


def test_proxy_order_flow_is_discounted():
    real = evaluate().score
    proxy_flow = OrderFlowState(delta=500.0, cvd=5000.0, cvd_slope=0.9, delta_z=2.5,
                                absorption=0.8, divergence=1.0, is_proxy=True)
    assert evaluate(order_flow=proxy_flow).score < real


def test_weights_must_be_positive():
    from icarus.config import ConfluenceWeights
    zeroed = ConfluenceWeights(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        ConfluenceEngine(zeroed)
