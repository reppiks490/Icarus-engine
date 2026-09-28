from datetime import datetime, timedelta, timezone

import pytest

from icarus.features.sentiment import SentimentOverlay, SentimentReading, constant_source

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def test_absent_feed_is_hard_neutral():
    overlay = SentimentOverlay()
    assert overlay.update(NOW) == 0.0
    assert overlay.alignment(1, NOW) == pytest.approx(0.5)
    assert overlay.alignment(-1, NOW) == pytest.approx(0.5)


def test_reading_must_be_bounded():
    with pytest.raises(ValueError):
        SentimentReading(value=1.5, ts=NOW)


def test_fresh_bullish_reading_favours_longs():
    overlay = SentimentOverlay()
    overlay.push(SentimentReading(value=1.0, ts=NOW, source="test"))
    assert overlay.alignment(1, NOW) == pytest.approx(1.0)
    assert overlay.alignment(-1, NOW) == pytest.approx(0.0)


def test_influence_decays_toward_neutral_with_age():
    overlay = SentimentOverlay(half_life=timedelta(hours=6))
    overlay.push(SentimentReading(value=1.0, ts=NOW, source="test"))
    assert overlay.update(NOW + timedelta(hours=6)) == pytest.approx(0.5)
    assert overlay.update(NOW + timedelta(hours=12)) == pytest.approx(0.25)
    assert overlay.update(NOW + timedelta(days=7)) < 0.01


def test_readings_from_the_future_are_ignored():
    overlay = SentimentOverlay()
    overlay.push(SentimentReading(value=1.0, ts=NOW + timedelta(hours=1), source="test"))
    assert overlay.update(NOW) == 0.0


def test_max_influence_caps_the_overlay():
    overlay = SentimentOverlay(source=constant_source(1.0), max_influence=0.25)
    assert overlay.update(NOW) == pytest.approx(0.25)
    assert overlay.alignment(1, NOW) == pytest.approx(0.625)


def test_alignment_rejects_a_bad_direction():
    with pytest.raises(ValueError):
        SentimentOverlay().alignment(0, NOW)
