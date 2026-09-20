from datetime import datetime, timedelta, timezone

import pytest

from icarus.data import Bar
from icarus.features.structure import MarketStructure, StructureEvent, SwingDetector, SwingType

START = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)


def bars_from(prices, *, spread=0.5):
    """Build bars whose highs/lows straddle the given closes by a fixed spread."""
    out = []
    for index, price in enumerate(prices):
        out.append(Bar(ts=START + timedelta(minutes=5 * index), open=price,
                       high=price + spread, low=price - spread, close=price, volume=100.0))
    return out


def test_swing_detector_confirms_a_peak_with_the_required_lag():
    detector = SwingDetector(strength=2)
    confirmed = []
    # Prices rise to a clear peak at index 2, then fall away.
    for index, bar in enumerate(bars_from([10.0, 11.0, 14.0, 11.0, 10.0])):
        for swing in detector.update(bar):
            confirmed.append((index, swing))
    assert len(confirmed) == 1
    confirmation_index, swing = confirmed[0]
    assert swing.kind is SwingType.HIGH
    assert swing.index == 2
    assert confirmation_index == 4          # confirmed exactly `strength` bars later
    assert swing.price == pytest.approx(14.5)


def test_swing_detector_finds_troughs():
    detector = SwingDetector(strength=1)
    found = []
    for bar in bars_from([10.0, 8.0, 10.0]):
        found.extend(detector.update(bar))
    assert [swing.kind for swing in found] == [SwingType.LOW]


def test_swing_detector_rejects_zero_strength():
    with pytest.raises(ValueError):
        SwingDetector(strength=0)


def test_market_structure_emits_bos_then_choch():
    structure = MarketStructure(strength=1, lookback=20)
    # Confirm a pivot low, close beneath it, then reclaim above a pivot high.
    prices = [10.0, 9.0, 10.0, 11.0, 8.0, 9.0, 12.0, 13.0]
    events = [structure.update(bar) for bar in bars_from(prices)]
    assert StructureEvent.NONE in events
    assert any(event in (StructureEvent.BOS_DOWN, StructureEvent.CHOCH_DOWN) for event in events)
    assert any(event in (StructureEvent.BOS_UP, StructureEvent.CHOCH_UP) for event in events)
    assert structure.trend == 1


def test_structure_breaks_require_a_close_not_a_wick():
    structure = MarketStructure(strength=1, lookback=20)
    for bar in bars_from([10.0, 12.0, 10.0]):
        structure.update(bar)
    assert structure.swing_highs, "a pivot high should be confirmed by now"
    level = structure.swing_highs[-1].price
    # A bar that trades far above the pivot but closes below it is a raid.
    wick = Bar(ts=START + timedelta(minutes=60), open=10.0, high=level + 5.0,
               low=9.5, close=level - 0.1, volume=100.0)
    assert structure.update(wick) is StructureEvent.NONE


def test_alignment_rewards_the_trend_and_punishes_the_other_side():
    structure = MarketStructure(strength=1, lookback=20)
    for bar in bars_from([10.0, 12.0, 10.5, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]):
        structure.update(bar)
    assert structure.trend == 1
    assert structure.alignment(1) > structure.alignment(-1)
    assert 0.0 <= structure.alignment(-1) <= 1.0


def test_alignment_rejects_a_bad_direction():
    with pytest.raises(ValueError):
        MarketStructure().alignment(0)
