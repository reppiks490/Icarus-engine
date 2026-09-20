"""Synthetic workflow tests; these do not establish market performance."""
import math
from copy import deepcopy
import pytest

from icarus_engine.research import Windows, Policy, digest, entry_metrics, run_search, return_correlation, wilson


SOURCE = {"spec": {"symbol": "NQ"}, "runner_config": {}, "base_inputs": {"conf_min_votes": 4},
          "pts_scale": 1.0, "mintick": .25}
BASELINE_HASH = digest({"spec": SOURCE["spec"], "base_inputs": SOURCE["base_inputs"],
                        "replay_config": SOURCE["runner_config"], "pts_scale": 1.0, "mintick": .25})


def replay(evaluate, asset="NQ"):
    """Attach deterministic frozen replay evidence to synthetic result fixtures."""
    def wrapped(patch, start, end, **costs):
        out = deepcopy(evaluate(patch, start, end))
        cfg = out["config"]
        cfg.update(chart_type="real", session="24/7", tf=1, point_value=1, leverage=50,
                   pts_scale=1.0, window_start=start, window_end=end, overrides=patch, **costs)
        effective = {"base_inputs": {**SOURCE["base_inputs"], **patch}, "pts_scale": 1.0,
                     "window_start": start, "window_end": end, "leverage": 50}
        cfg["reproducibility"] = {"source_config": SOURCE, "source_config_sha256": digest(SOURCE),
                                  "effective_config": effective, "effective_config_sha256": digest(effective),
                                  "subbars_sha256": "c"*64, "deep_sha256": "d"*64}
        out["asset"] = asset
        return out
    return wrapped


def small_policy(**values):
    return Policy(**{"min_entries": 3, "min_net_improvement_pct": 0, **values})


def result(pnls, *, valid=True, open_residue=False):
    rows = [{"type": "long", "entry_ts": i + 1, "entry_px": 100, "entry_signal": "Long",
             "exit_ts": i + 2, "pnl": pnl, "open": False} for i, pnl in enumerate(pnls)]
    if open_residue:
        rows.append({**rows[0], "exit_ts": None, "pnl": -1000, "open": True})
    return {"config": {"fill_on": "real", "capital": 1000, "commission": 2, "slippage_ticks": 2,
                       "historical_scale_asof_valid": valid}, "trades": rows,
            "summary": {"max_drawdown": {"all": 20}}, "equity": [[1, 1000], [2, 980]]}


def test_wilson_small_sample_and_empty():
    assert wilson(0, 0) is None
    assert wilson(9, 10) == pytest.approx([0.595849973, 0.982123787], abs=1e-8)
    assert wilson(10, 10)[0] < 0.9
    with pytest.raises(ValueError):
        wilson(True, 5)


def test_partial_exits_not_independent_and_open_residue_excluded():
    r = result([10, -20], open_residue=True)
    r["trades"].append({**r["trades"][1], "pnl": 5})
    m = entry_metrics(r)
    assert m["entries"] == 1 and m["open_entry_cohorts"] == 1
    assert m["net_after_costs"] == -15 and m["win_rate"] == 0
    r["equity"].append([3, -100])
    assert entry_metrics(r)["max_drawdown_pct"] == pytest.approx(110)


def test_empty_and_nonreal_results():
    assert entry_metrics(result([]))["win_rate"] is None
    r = result([1]); r["config"]["fill_on"] = "chart"
    with pytest.raises(ValueError, match="real-price"):
        entry_metrics(r)


def test_selection_does_not_inspect_other_candidates_holdouts(tmp_path):
    calls = []
    def evaluate(patch, start, end):
        calls.append((patch.get("conf_min_votes"), start, end))
        # Candidate 6 is the training/validation winner but loses holdout.
        pnl = 6 if patch.get("conf_min_votes") == 6 else 2 if patch else 1
        if start == 50: pnl = -1 if patch.get("conf_min_votes") == 6 else 99 if patch else 1
        return result([pnl] * 3)
    out = run_search("NQ", {"conf_min_votes": [5, 6]}, Windows(1, 10, 20, 30, 50, 60), replay(evaluate),
                     dataset_hash="a"*64, baseline_hash=BASELINE_HASH, holdout_ledger=tmp_path / "holdouts.db",
                     policy=small_policy())
    assert out["selected"] == {"conf_min_votes": 6}
    assert [(v, start) for v, start, _ in calls if start == 50] == [(None, 50), (6, 50)]
    assert not out["research_qualified"] and not out["execution_authorized"]
    # New rows outside the holdout change a full-cache hash, not its visibility.
    with pytest.raises(ValueError, match="holdout already consumed"):
        run_search("NQ", {"conf_min_votes": [5]}, Windows(1, 10, 20, 30, 50, 60), replay(evaluate),
                   dataset_hash="c"*64, baseline_hash=BASELINE_HASH, holdout_ledger=tmp_path / "holdouts.db",
                   policy=small_policy())
    with pytest.raises(ValueError, match="holdout already consumed"):
        run_search("NQ", {"conf_min_votes": [5]}, Windows(1, 10, 20, 30, 51, 61), replay(evaluate),
                   dataset_hash="a"*64, baseline_hash=BASELINE_HASH, holdout_ledger=tmp_path / "holdouts.db",
                   policy=small_policy())


def test_missing_asof_provenance_prevents_qualification(tmp_path):
    out = run_search("GC", {"conf_min_votes": [5]}, Windows(1, 10, 20, 30, 50, 60),
                     replay(lambda patch, *args: result([10 if patch else 1]*3, valid=False), "GC"),
                     dataset_hash="a"*64, baseline_hash=BASELINE_HASH,
                     holdout_ledger=tmp_path / "h.db", policy=small_policy())
    assert out["status"] == "complete" and not out["research_qualified"]


def test_open_loss_cannot_be_hidden_by_closed_winners(tmp_path):
    def evaluate(*args):
        r = result([20, 20, 20, 20], open_residue=True)
        r["trades"][-1]["pnl"] = -90
        return r
    out = run_search("GC", {"conf_min_votes": [5]}, Windows(1, 10, 20, 30, 50, 60),
                     replay(evaluate, "GC"), dataset_hash="a"*64, baseline_hash=BASELINE_HASH,
                     holdout_ledger=tmp_path / "h.db", policy=small_policy())
    assert out["status"] == "no_candidate" and out["holdout"] is None


def test_trial_cap_and_cancel_do_not_run_unbounded(tmp_path):
    calls = []
    def evaluate(*args):
        calls.append(args)
        return result([-1])
    out = run_search("GC", {"conf_min_votes": [3, 4, 5, 6]}, Windows(1, 10, 20, 30, 50, 60),
                     replay(evaluate, "GC"), dataset_hash="a"*64, baseline_hash=BASELINE_HASH,
                     holdout_ledger=tmp_path / "h.db", policy=Policy(max_trials=2, min_entries=1))
    assert len(calls) == 6 and out["status"] == "no_candidate" and out["search_truncated"]
    out = run_search("GC", {"conf_min_votes": [3]}, Windows(1, 10, 20, 30, 50, 60),
                     replay(evaluate, "GC"), dataset_hash="a"*64, baseline_hash=BASELINE_HASH,
                     holdout_ledger=tmp_path / "h.db", cancelled=lambda: True)
    assert out["status"] == "cancelled" and len(calls) == 6
    assert out["holdout"] is None


def test_old_validation_cannot_be_relabelled_as_holdout(tmp_path):
    ledger = tmp_path / "h.db"
    # First attempt examines through 30 but fails selection (no final holdout).
    run_search("NQ", {"conf_min_votes": [5]}, Windows(1, 10, 20, 30, 50, 60),
               replay(lambda *a: result([-1]*3)), dataset_hash="a"*64, baseline_hash=BASELINE_HASH,
               holdout_ledger=ledger, policy=small_policy())
    with pytest.raises(ValueError, match="previously evaluated"):
        run_search("NQ", {"conf_min_votes": [5]}, Windows(1, 4, 5, 10, 20, 30),
                   replay(lambda patch, *a: result([10 if patch else 1]*3)), dataset_hash="c"*64, baseline_hash=BASELINE_HASH,
                   holdout_ledger=ledger, policy=small_policy())


@pytest.mark.parametrize("grid", [{"bogus": [1]}, {"conf_min_votes": [True]}, {"conf_min_votes": [2, 2]},
                                 {"trail_atr_mult": [math.inf]}, {}])
def test_bad_grid_rejected_before_evaluation(tmp_path, grid):
    with pytest.raises(ValueError):
        run_search("NQ", grid, Windows(1, 10, 20, 30, 50, 60), lambda *args: pytest.fail("evaluation ran"),
                   dataset_hash="a"*64, baseline_hash="b"*64, holdout_ledger=tmp_path / "h.db")


def test_disjoint_windows():
    with pytest.raises(ValueError): Windows(1, 10, 10, 30, 50, 60)
    with pytest.raises(ValueError): Windows(True, 10, 20, 30, 50, 60)


def test_return_correlation_uses_availability_and_exact_intervals():
    left = [(10, 10, 100), (20, 20, 110), (30, 30, 99), (40, 80, 200)]
    right = [(10, 10, 100), (20, 20, 90), (30, 30, 99), (40, 40, 200)]
    r = return_correlation(left, right, as_of=50, min_pairs=2)
    assert r["pairs"] == 2 and r["correlation"] == pytest.approx(-1)
    right = [(10, 10, 100), (30, 30, 99)]
    assert return_correlation(left, right, as_of=50, min_pairs=2)["pairs"] == 0


def test_correlation_rejects_ambiguous_revisions():
    with pytest.raises(ValueError, match="duplicate"):
        return_correlation([(1, 1, 100), (1, 2, 101)], [], as_of=10)


def search(tmp_path, evaluate, *, stress=None, policy=None, **kwargs):
    return run_search("NQ", {"conf_min_votes": [5, 6]}, Windows(1, 10, 20, 30, 50, 60), evaluate,
                      dataset_hash="a"*64, baseline_hash=BASELINE_HASH, holdout_ledger=tmp_path / "h.db",
                      stress_evaluate=stress, policy=policy or Policy(min_entries=3), **kwargs)


def test_paired_baselines_stress_and_preregistered_holdout_evidence(tmp_path):
    import sqlite3
    calls, checkpoints = [], []
    ordinary = replay(lambda patch, *_: result([patch.get("conf_min_votes", 1) * 2] * 3))
    stressed = replay(lambda patch, *_: result([patch.get("conf_min_votes", 1)] * 3))

    def evaluate(patch, start, end, **costs):
        scenario = "stress" if costs else "normal"
        calls.append((scenario, patch.get("conf_min_votes"), start))
        if start == 50:
            assert checkpoints[-1]["selected"] == {"conf_min_votes": 6}
            assert checkpoints[-1]["selection"]["selection_sha256"]
            assert checkpoints[-1]["holdout_consumed"]
            with sqlite3.connect(tmp_path / "h.db") as db:
                assert db.execute("SELECT count(*) FROM holdouts").fetchone()[0] == 1
        return (stressed if costs else ordinary)(patch, start, end, **costs)

    out = search(tmp_path, evaluate, stress=evaluate, checkpoint=checkpoints.append)
    assert out["research_qualified"] and not out["accuracy_guaranteed"] and not out["execution_authorized"]
    assert out["qualification_reasons"] == []
    assert out["selected"] == {"conf_min_votes": 6}
    assert set(out["baseline"]) == {"train", "validation", "holdout"}
    assert set(out["baseline_evidence"]) == {"train", "validation", "holdout"}
    for scenario in ("normal", "stress"):
        for start in (1, 20, 50):
            assert calls.count((scenario, None, start)) == 1
    assert [call for call in calls if call[2] == 50] == [
        ("normal", None, 50), ("normal", 6, 50), ("stress", None, 50), ("stress", 6, 50)]
    assert out["stress"]["costs"] == {"commission": 3, "slippage_ticks": 3}
    assert out["holdout_comparison"]["passed"] and out["stress"]["holdout_comparison"]["passed"]
    assert out["holdout_evidence"]["config"]["commission"] == 2
    assert out["stress"]["holdout_evidence"]["config"]["commission"] == 3
    assert out["selection"]["selection_sha256"] == digest({k: v for k, v in out["selection"].items() if k != "selection_sha256"})


@pytest.mark.parametrize("candidate,baseline", [(1, 2), (2, 2), (2.01, 2)])
def test_profitable_candidate_without_meaningful_improvement_is_rejected(tmp_path, candidate, baseline):
    evaluate = replay(lambda patch, *_: result([candidate if patch else baseline] * 3))
    out = search(tmp_path, evaluate)
    assert out["status"] == "no_candidate" and not out["holdout_consumed"]
    assert all(not trial["paired_comparison"]["validation"]["passed"] for trial in out["trials"])
    assert all(trial["paired_comparison"]["validation"]["reasons"] for trial in out["trials"])


def test_zero_hurdles_still_require_strict_improvement(tmp_path):
    out = search(tmp_path, replay(lambda *_: result([5] * 3)),
                 policy=small_policy(min_expectancy_improvement_pct=0))
    assert out["status"] == "no_candidate"


@pytest.mark.parametrize("baseline", [[], [0, 0, 0], [-1, -1, -1]])
def test_no_trade_zero_and_losing_baselines_use_absolute_expectancy_hurdle(tmp_path, baseline):
    evaluate = replay(lambda patch, *_: result([5, 5, 5] if patch else baseline))
    out = search(tmp_path, evaluate, stress=evaluate,
                 policy=small_policy(min_expectancy_improvement=4))
    assert out["research_qualified"]
    comparison = out["holdout_comparison"]
    assert comparison["expectancy_improvement_required"] == 4
    assert comparison["baseline_expectancy_missing"] == (not baseline)


def test_stress_costs_filter_selection_before_holdout(tmp_path):
    ordinary = replay(lambda patch, *_: result([patch.get("conf_min_votes", 1) * 3] * 3))
    stressed = replay(lambda patch, *_: result([0 if patch.get("conf_min_votes") == 6 else 8 if patch else 1] * 3))
    out = search(tmp_path, ordinary, stress=stressed)
    assert out["selected"] == {"conf_min_votes": 5} and out["research_qualified"]
    trial = next(t for t in out["trials"] if t["inputs"] == {"conf_min_votes": 6})
    assert not trial["eligible"] and not trial["stress"]["validation"]["paired_comparison"]["passed"]


def test_failed_stress_holdout_never_selects_another_candidate(tmp_path):
    calls = []
    ordinary = replay(lambda patch, *_: result([patch.get("conf_min_votes", 1) * 3] * 3))
    stressed = replay(lambda patch, start, _: result([-1 if start == 50 and patch else patch.get("conf_min_votes", 1) * 2] * 3))
    def cost_replay(patch, start, end, **costs):
        calls.append((patch.get("conf_min_votes"), start))
        return stressed(patch, start, end, **costs)
    out = search(tmp_path, ordinary, stress=cost_replay)
    assert out["selected"] == {"conf_min_votes": 6} and not out["research_qualified"]
    assert out["holdout_comparison"]["passed"]
    assert not out["stress"]["holdout_comparison"]["passed"]
    assert [(candidate, start) for candidate, start in calls if start == 50] == [(None, 50), (6, 50)]
    assert "stress-cost holdout failed paired improvement hurdles" in out["qualification_reasons"]


@pytest.mark.parametrize("require_stress", [True, False])
def test_missing_or_disabled_stress_cannot_qualify(tmp_path, require_stress):
    evaluate = replay(lambda patch, *_: result([10 if patch else 1] * 3))
    out = search(tmp_path, evaluate, policy=Policy(min_entries=3, require_stress=require_stress))
    assert out["status"] == "complete" and not out["research_qualified"]
    assert out["stress"]["status"] == ("unavailable" if require_stress else "disabled")


def test_baseline_asof_provenance_is_required_too(tmp_path):
    evaluate = replay(lambda patch, *_: result([10 if patch else 1] * 3, valid=bool(patch)))
    out = search(tmp_path, evaluate, stress=evaluate)
    assert not out["research_qualified"]
    assert "historical scale lacks valid as-of provenance" in out["qualification_reasons"]


@pytest.mark.parametrize("field", ["asset", "window", "cost", "data", "snapshot", "inputs", "capital"])
def test_unpaired_replay_provenance_fails_before_an_improvement_claim(tmp_path, field):
    good = replay(lambda patch, *_: result([10 if patch else 1] * 3))
    checkpoints = []
    def evaluate(patch, start, end):
        out = good(patch, start, end)
        if patch:
            cfg = out["config"]
            if field == "asset": out["asset"] = "ES"
            if field == "window": cfg["window_start"] += 1
            if field == "cost": cfg["commission"] = 0
            if field == "capital": cfg["capital"] = 2000
            if field == "data": cfg["reproducibility"]["subbars_sha256"] = "f"*64
            if field == "snapshot": cfg["reproducibility"]["source_config_sha256"] = "f"*64
            if field == "inputs": cfg["reproducibility"]["effective_config"]["base_inputs"] = {}
        return out
    with pytest.raises(ValueError, match="mismatch|missing"):
        search(tmp_path, evaluate, checkpoint=checkpoints.append)
    assert checkpoints and all(not item["research_qualified"] and item["selected"] is None for item in checkpoints)


def test_cancel_after_selection_does_not_claim_holdout(tmp_path):
    stop = False
    def checkpoint(out):
        nonlocal stop
        if out["selection"]: stop = True
    evaluate = replay(lambda patch, *_: result([10 if patch else 1] * 3))
    out = search(tmp_path, evaluate, checkpoint=checkpoint, cancelled=lambda: stop)
    assert out["status"] == "cancelled" and out["selected"] and not out["holdout_consumed"]


def test_cancelled_holdout_batch_stays_consumed(tmp_path):
    calls, stop = [], False
    good = replay(lambda patch, *_: result([10 if patch else 1] * 3))
    def evaluate(patch, start, end):
        nonlocal stop
        calls.append((patch, start))
        if start == 50: stop = True
        return good(patch, start, end)
    out = search(tmp_path, evaluate, cancelled=lambda: stop)
    assert out["status"] == "cancelled" and out["holdout_consumed"] and out["holdout"] is None
    assert [patch for patch, start in calls if start == 50] == [{}]
    with pytest.raises(ValueError, match="holdout already consumed"):
        search(tmp_path, good)


def test_budget_exhaustion_between_baselines_prevents_trial_and_holdout(tmp_path, monkeypatch):
    import icarus_engine.research as module
    now, calls = [0.0], []
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    good = replay(lambda patch, *_: result([10 if patch else 1] * 3))
    def evaluate(patch, start, end):
        calls.append((patch, start)); now[0] = 2
        return good(patch, start, end)
    out = search(tmp_path, evaluate, policy=Policy(max_seconds=1))
    assert out["status"] == "time_limit" and not out["holdout_consumed"]
    assert calls == [({}, 1)] and out["trials"] == []


@pytest.mark.parametrize("values", [
    {"min_net_improvement_pct": -1}, {"min_net_improvement_pct": math.inf},
    {"min_expectancy_improvement_pct": math.nan}, {"min_expectancy_improvement": True},
    {"min_expectancy_improvement": -1}, {"max_drawdown_increase_pct": -1},
    {"stress_commission_multiplier": .9}, {"stress_commission_multiplier": 11},
    {"stress_slippage_ticks": 0}, {"stress_slippage_ticks": 1.5}, {"require_stress": 1}])
def test_improvement_and_stress_policy_validation(values):
    with pytest.raises(ValueError): Policy(**values)
