from datetime import datetime, timezone

import pytest

from icarus.data import Bar, load_csv, parse_timestamp, synthetic_for, synthetic_series, to_csv


def make_bar(**kwargs) -> Bar:
    defaults = dict(ts=datetime(2026, 1, 1, tzinfo=timezone.utc), open=10.0, high=11.0,
                    low=9.0, close=10.5, volume=100.0)
    defaults.update(kwargs)
    return Bar(**defaults)


def test_bar_rejects_naive_timestamps():
    with pytest.raises(ValueError):
        Bar(ts=datetime(2026, 1, 1), open=1.0, high=2.0, low=0.5, close=1.5, volume=1.0)


def test_bar_rejects_inconsistent_ohlc():
    with pytest.raises(ValueError):
        make_bar(high=9.0, low=9.5)


def test_clv_endpoints():
    assert make_bar(open=9.0, high=11.0, low=9.0, close=11.0).clv == pytest.approx(1.0)
    assert make_bar(open=11.0, high=11.0, low=9.0, close=9.0).clv == pytest.approx(-1.0)
    assert make_bar(open=10.0, high=11.0, low=9.0, close=10.0).clv == pytest.approx(0.0)
    flat = make_bar(open=10.0, high=10.0, low=10.0, close=10.0)
    assert flat.clv == 0.0                       # zero range must not divide by zero


def test_wicks_and_body():
    bar = make_bar(open=9.5, high=11.0, low=9.0, close=10.5)
    assert bar.upper_wick == pytest.approx(0.5)
    assert bar.lower_wick == pytest.approx(0.5)
    assert bar.body == pytest.approx(1.0)


@pytest.mark.parametrize("raw", [
    "2026-01-05 13:30:00",
    "2026-01-05T13:30:00Z",
    "2026-01-05T13:30:00+00:00",
    "1767620000",
    "1767620000000",
])
def test_parse_timestamp_accepts_common_forms(raw):
    parsed = parse_timestamp(raw)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0.0


def test_parse_timestamp_rejects_garbage():
    with pytest.raises(ValueError):
        parse_timestamp("not-a-time")


def test_synthetic_series_is_deterministic_for_a_seed():
    first = synthetic_series(200, seed=3)
    second = synthetic_series(200, seed=3)
    assert [bar.close for bar in first] == [bar.close for bar in second]
    assert [bar.close for bar in first] != [bar.close for bar in synthetic_series(200, seed=4)]


def test_synthetic_series_is_internally_consistent_and_ordered():
    bars = synthetic_series(500, seed=5)
    assert len(bars) == 500
    for bar in bars:
        assert bar.low <= bar.open <= bar.high
        assert bar.low <= bar.close <= bar.high
        assert bar.volume > 0.0
    assert all(b.ts < c.ts for b, c in zip(bars, bars[1:]))


def test_synthetic_for_uses_the_asset_price_scale():
    assert synthetic_for("forex", 50)[0].open == pytest.approx(1.085)
    assert synthetic_for("crypto", 50)[0].open == pytest.approx(64000.0)


def test_csv_round_trip(tmp_path):
    original = synthetic_series(50, seed=9)
    path = tmp_path / "bars.csv"
    to_csv(original, str(path))
    restored = load_csv(str(path))
    assert len(restored) == len(original)
    assert restored[0].ts == original[0].ts
    assert restored[-1].close == pytest.approx(original[-1].close)
    assert restored[0].ask_volume == pytest.approx(original[0].ask_volume)


def test_load_csv_reports_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("time,open,high\n2026-01-01,1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing column"):
        load_csv(str(path))
