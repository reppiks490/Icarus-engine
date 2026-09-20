import pytest

from icarus_engine.microstructure import TradeEvent, TradeAggregator


def tick(seq, ns, price=100, qty=1, side="unknown", received=None):
    return TradeEvent("TEST", "NQZ26", seq, ns, received if received is not None else ns + 10, price, qty, side)


def test_seconds_footprint_and_unknown_aggressor():
    a = TradeAggregator("TEST", "NQZ26")
    assert a.push(tick(1, 0, 100, 2, "buy")) == []
    assert a.push(tick(2, 999_999_999, 101, 3)) == []
    bars = a.push(tick(3, 1_000_000_000, 99, 4, "sell"))
    assert len(bars) == 1
    b = bars[0]
    assert (b["open_ticks"], b["high_ticks"], b["low_ticks"], b["close_ticks"], b["volume"]) == (100, 101, 100, 101, 5)
    assert b["footprint"] == {"100": {"buy": 2, "sell": 0, "unknown": 0}, "101": {"buy": 0, "sell": 0, "unknown": 3}}
    assert not b["aggressor_complete"] and b["available_at_ns"] == 1_000_000_010
    assert a.status()["active_bucket_is_partial"]


def test_duplicate_and_gap_never_create_fake_volume():
    a = TradeAggregator("TEST", "NQZ26")
    event = tick(1, 0)
    a.push(event); assert a.push(event) == []
    assert a.bucket["volume"] == 1
    with pytest.raises(ValueError, match="conflicting"):
        a.push(tick(1, 0, qty=2))
    with pytest.raises(ValueError, match="sequence gap"):
        a.push(tick(3, 2_000_000_000))
    with pytest.raises(ValueError, match="gap"):
        a.advance(3_000_000_000, 3_000_000_010)
    assert a.status()["sequence_gap"]


def test_no_empty_intervals_or_local_clock_fills():
    a = TradeAggregator("TEST", "NQZ26")
    a.push(tick(1, 0))
    assert len(a.push(tick(2, 20_000_000_000))) == 1
    assert a.bucket["start_ns"] == 20_000_000_000
    assert a.advance(20_999_999_999, 21_000_000_000) == []
    assert len(a.advance(21_000_000_000, 21_000_000_010)) == 1
    with pytest.raises(ValueError, match="late"):
        a.push(tick(3, 20_999_999_999))


def test_receipt_cannot_move_backwards_after_watermark():
    a = TradeAggregator("TEST", "NQZ26")
    a.push(tick(1, 0))
    a.advance(1_000_000_000, 10_000_000_000)
    with pytest.raises(ValueError, match="receipt ordering"):
        a.push(tick(2, 2_000_000_000))
    assert a.last.sequence == 1 and a.bucket is None


def test_conflicting_duplicate_halts_uncertain_stream():
    a = TradeAggregator("TEST", "NQZ26")
    a.push(tick(1, 0))
    with pytest.raises(ValueError, match="conflicting"):
        a.push(tick(1, 0, qty=2))
    with pytest.raises(ValueError, match="gap"):
        a.push(tick(2, 2_000_000_000))


@pytest.mark.parametrize("change", [{"quantity": float("nan")}, {"quantity": True}, {"event_ns": 1.5},
                                     {"received_ns": -1}, {"price_ticks": True}, {"aggressor": "up"}])
def test_invalid_events(change):
    values = dict(venue="TEST", instrument="NQ", sequence=1, event_ns=0, received_ns=1, price_ticks=0, quantity=1)
    with pytest.raises(ValueError): TradeEvent(**{**values, **change})


def test_negative_futures_prices_are_valid_and_cross_instrument_rejected():
    a = TradeAggregator("TEST", "NQZ26")
    a.push(tick(1, 0, -3))
    with pytest.raises(ValueError, match="wrong venue"):
        a.push(TradeEvent("TEST", "ESZ26", 2, 1, 2, 100, 1))
