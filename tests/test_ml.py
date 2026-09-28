from datetime import datetime, timedelta, timezone

import pytest

from icarus.config import AssetClass, profile_for
from icarus.data import synthetic_for
from icarus.ml import (
    FEATURE_COLUMNS, LABEL_COLUMNS, MLGate, ModelVote, export_training_set, triple_barrier,
)

NOW = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
BARS = synthetic_for(AssetClass.MICRO_FUTURES, 3000, seed=11)


# --- the vote contract ------------------------------------------------------

def test_vote_edge_matches_the_suite_hud_semantics():
    """The HUD reads XGB5:67L/44S. That is a +0.207 lean, not a 67% signal."""
    assert ModelVote(67, 44, NOW).edge == pytest.approx((67 - 44) / 111)


def test_a_tied_or_silent_vote_has_no_edge():
    assert ModelVote(50, 50, NOW).edge == 0.0
    assert ModelVote(0, 0, NOW).edge == 0.0


def test_vote_validates_its_inputs():
    with pytest.raises(ValueError):
        ModelVote(-1, 10, NOW)
    with pytest.raises(ValueError):
        ModelVote(10, 10, NOW, confidence=1.5)


# --- the gate ---------------------------------------------------------------

def test_no_model_attached_is_a_hard_neutral():
    gate = MLGate()
    assert gate.update({}, NOW) == 0.0
    assert gate.alignment(1, {}, NOW) == pytest.approx(0.5)
    assert gate.alignment(-1, {}, NOW) == pytest.approx(0.5)


def test_a_bullish_model_favours_longs_without_vetoing_shorts_outright():
    gate = MLGate()
    gate.push(ModelVote(100, 0, NOW))
    assert gate.alignment(1, {}, NOW) == pytest.approx(1.0)
    assert gate.alignment(-1, {}, NOW) == pytest.approx(0.0)


def test_a_stale_model_decays_to_neutral():
    gate = MLGate(half_life=timedelta(minutes=30))
    gate.push(ModelVote(100, 0, NOW))
    assert gate.update({}, NOW + timedelta(minutes=30)) == pytest.approx(0.5)
    assert gate.update({}, NOW + timedelta(hours=6)) < 0.01


def test_votes_from_the_future_are_ignored():
    gate = MLGate()
    gate.push(ModelVote(100, 0, NOW + timedelta(minutes=5)))
    assert gate.update({}, NOW) == 0.0


def test_confidence_and_influence_both_scale_the_vote():
    strong = MLGate(); strong.push(ModelVote(100, 0, NOW, confidence=1.0))
    timid = MLGate(); timid.push(ModelVote(100, 0, NOW, confidence=0.25))
    capped = MLGate(max_influence=0.5); capped.push(ModelVote(100, 0, NOW))
    assert timid.update({}, NOW) < strong.update({}, NOW)
    assert capped.update({}, NOW) == pytest.approx(0.5)


def test_a_model_below_the_confidence_floor_abstains():
    gate = MLGate(min_confidence=0.6)
    gate.push(ModelVote(100, 0, NOW, confidence=0.3))
    assert gate.alignment(1, {}, NOW) == pytest.approx(0.5)


def test_gate_rejects_a_bad_direction():
    with pytest.raises(ValueError):
        MLGate().alignment(0, {}, NOW)


def test_ml_weight_is_zero_by_default_so_an_absent_model_changes_nothing():
    for asset in AssetClass:
        assert profile_for(asset).weights.ml == 0.0


# --- labels -----------------------------------------------------------------

def test_triple_barrier_refuses_a_horizon_past_the_data():
    assert triple_barrier(BARS, len(BARS) - 2, atr=10.0, horizon=24) is None


def test_triple_barrier_refuses_a_degenerate_atr():
    assert triple_barrier(BARS, 10, atr=0.0) is None


def test_triple_barrier_returns_a_well_formed_label():
    label = triple_barrier(BARS, 100, atr=30.0, upper_atr=2.0, lower_atr=1.0, horizon=24)
    assert label is not None
    assert label.label in (-1, 0, 1)
    assert 1 <= label.bars_to_hit <= 24
    assert label.mfe_atr >= 0.0 >= label.mae_atr


def test_triple_barrier_resolves_an_ambiguous_bar_pessimistically():
    """When one bar spans both barriers, the adverse side must win."""
    from icarus.data import Bar
    base = Bar(ts=NOW, open=100.0, high=100.5, low=99.5, close=100.0, volume=1.0)
    spanning = Bar(ts=NOW + timedelta(minutes=5), open=100.0, high=130.0, low=70.0,
                   close=100.0, volume=1.0)
    tail = [Bar(ts=NOW + timedelta(minutes=10 + i * 5), open=100.0, high=100.5,
                low=99.5, close=100.0, volume=1.0) for i in range(30)]
    label = triple_barrier([base, spanning, *tail], 0, atr=10.0, upper_atr=2.0,
                           lower_atr=1.0, horizon=5)
    assert label is not None and label.label == -1


# --- export -----------------------------------------------------------------

def test_export_writes_the_declared_contract(tmp_path):
    import csv

    path = tmp_path / "train.csv"
    rows = export_training_set(BARS, profile_for(AssetClass.MICRO_FUTURES), str(path))
    assert rows > 0
    with open(path, encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["ts", *FEATURE_COLUMNS, *LABEL_COLUMNS]
        first = next(reader)
    assert first["label"] in ("-1", "0", "1")
    assert float(first["atr"]) > 0.0


def test_export_all_bars_yields_more_rows_than_trigger_bars_only(tmp_path):
    profile = profile_for(AssetClass.MICRO_FUTURES)
    triggers = export_training_set(BARS, profile, str(tmp_path / "a.csv"), sweeps_only=True)
    every = export_training_set(BARS, profile, str(tmp_path / "b.csv"), sweeps_only=False)
    assert every > triggers > 0
