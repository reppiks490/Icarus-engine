"""Real runner/emulator adoption, isolated journals, durable failure/restart guards."""
from copy import deepcopy
from dataclasses import asdict
import json
import time

import pytest

from icarus_engine.activation import ActivationStore
from icarus_engine.activation_runtime import ActivationRuntime, load_startup_overlay
from icarus_engine.advisory import canonical_hash, _iso
from icarus_engine.assets import AssetSpec
from icarus_engine.backtest import freeze_replay_port
from icarus_engine.emulator import PendingClose
from icarus_engine.pine.timeframe import Bar
from icarus_engine.research import digest
from icarus_engine.runtime import AssetRunner, Journal, Portfolio, RunnerConfig
from icarus_engine.strategy.inputs import Inputs


def make_port(root):
    journal = Journal(":memory:")
    port = Portfolio(journal, str(root))
    spec = AssetSpec("NQ", "Fixture", "yahoo", "NQ", "crypto", 1, 1,
                     chart_tf="1", commission=1, roll="none")
    inputs = Inputs(use_tide=False, use_eod_flat=False, conf_min_votes=8)
    runner = AssetRunner(RunnerConfig(spec, inputs, fixed_pts_scale=1, mintick=1), journal)
    for n in range(80):
        runner.on_sub_bar(Bar((n + 1) * 60, 100, 100, 100, 100, 10), 1, live=False)
    runner.warm, runner.live_from_ts = True, 5000
    port.runners["NQ"], port.order = runner, ["NQ"]
    assert runner.strat is not None and not runner.em.open and not runner.em._pending_entries
    return port, runner


def fingerprints(port, asset, _candidate=None):
    frozen = freeze_replay_port(port, asset)
    source = frozen.runners[asset]
    dataset = digest({"subbars": [(asdict(b), m) for b, m in source.subbars],
                      "deep": {str(k): [(asdict(b), m) for b, m in rows] for k, rows in source.deep.items()}})
    baseline = {"spec": asdict(source.spec), "base_inputs": source.inputs_base.to_dict(),
                "replay_config": asdict(source.cfg), "pts_scale": source.pts_scale, "mintick": source.mintick}
    return frozen, dataset, digest(baseline), baseline


def artifact(port, votes=9):
    _, dataset, baseline, _ = fingerprints(port, "NQ")
    candidate = {"asset": "NQ", "inputs": {"conf_min_votes": votes}, "dataset_hash": dataset,
                 "baseline_hash": baseline, "expires_at": _iso(time.time() + 3600)}
    version = canonical_hash(candidate)
    return {"artifact_type": "research_candidate", "research_qualified": True, "execution_authorized": False,
            "candidate_hash": version, "candidate": candidate,
            "reviews": [{"provider": "openai", "decision": "recommend", "candidate_hash": version},
                        {"provider": "anthropic", "decision": "approve", "candidate_hash": version}]}


@pytest.fixture
def setup(tmp_path):
    port, runner = make_port(tmp_path)
    (tmp_path / "inputs.NQ.json").write_text(json.dumps(runner.inputs_base.to_dict()), encoding="utf-8")
    (tmp_path / "inputs.ES.json").write_text('{"conf_min_votes":7}', encoding="utf-8")
    store = ActivationStore(tmp_path / "research" / "activation")
    approved = artifact(port)
    adapter = ActivationRuntime(port, lambda value: deepcopy(approved),
                                lambda asset, candidate: fingerprints(port, asset, candidate))
    yield store, port, runner, adapter, store.register(approved)
    port.journal.con.close()


def actual_history(runner):
    em = runner.em
    em.entry("ACTUAL", 1, 1)
    em.process_bar(Bar(4800, 100, 100, 100, 100, 1), runner.bar_index)
    em.close("ACTUAL", "manual")
    em.process_bar(Bar(4801, 105, 105, 105, 105, 1), runner.bar_index)
    runner._fills_seen, runner._closed_seen = len(em.fills), len(em.closed)
    runner.strat._prev_closed, runner.strat._p_netprofit = len(em.closed), em.netprofit
    runner.strat.daily_pnl = em.netprofit
    runner.recent_fills.append({"ts": 4801, "live": True, "comment": "actual"})
    runner.recent_events.append({"text": "actual event", "live": True})
    return em, em.closed, em.fills, em.netprofit, em._seq


def test_adoption_and_rollback_keep_actual_accounting_and_owner_files(setup, tmp_path, monkeypatch):
    store, port, runner, adapter, version = setup
    accounting = actual_history(runner)
    cfg = asdict(runner.cfg)
    recent = runner.recent_fills, runner.recent_events, list(runner.recent_fills), list(runner.recent_events)
    owner = {p: p.read_bytes() for p in tmp_path.glob("inputs*.json")}
    old_live = runner.live_from_ts
    monkeypatch.setattr(type(runner.feed), "daily_volume", lambda *a, **k: pytest.fail("network used"))
    operation = store.activate(version["version_id"], "apply", adapter.boundary)
    assert operation["status"] == "applied", operation
    assert runner.inputs_base.conf_min_votes == 9 and runner.strat.i.conf_min_votes == 9
    assert (runner.em, runner.em.closed, runner.em.fills, runner.em.netprofit, runner.em._seq) == accounting
    assert runner.strat.em is accounting[0] and runner.strat._prev_closed == len(runner.em.closed)
    assert runner.strat._p_netprofit == runner.em.netprofit and runner.strat.daily_pnl == runner.em.netprofit
    assert runner.recent_fills is recent[0] and runner.recent_events is recent[1]
    assert list(runner.recent_fills) == recent[2] and list(runner.recent_events) == recent[3]
    assert runner.live_from_ts == old_live
    profile = store.active_profile("NQ")["profile"]
    assert profile["cfg"]["inputs"] == profile["base_inputs"]
    assert canonical_hash(profile["owner_config"]) == profile["owner_config_hash"]
    assert profile["owner_config"]["runner_config"] == cfg
    with pytest.raises(ValueError, match="roll back"):
        port.rewarm_asset("NQ", {"conf_min_votes": 10})
    runner.set_paused(True); runner.flatten()
    result = store.rollback("NQ", "undo", adapter.boundary)
    assert result["status"] == "rolled_back", result
    assert runner.inputs_base.conf_min_votes == 8 and runner.paused
    assert (runner.em, runner.em.closed, runner.em.fills, runner.em.netprofit, runner.em._seq) == accounting
    assert asdict(runner.cfg) == cfg and not runner._activation_version_id
    assert all(p.read_bytes() == data for p, data in owner.items())


def test_adoption_and_rollback_preserve_actual_stop_cooldown(setup):
    store, _, runner, adapter, version = setup
    runner.strat.bars_since_stop = 0
    assert store.activate(version["version_id"], "cooldown-apply", adapter.boundary)["status"] == "applied"
    assert runner.strat.bars_since_stop == 0 and runner.state["bars_since_stop"] == 0
    runner.strat.bars_since_stop = 2
    assert store.rollback("NQ", "cooldown-rollback", adapter.boundary)["status"] == "rolled_back"
    assert runner.strat.bars_since_stop == 2


def test_adoption_detects_actual_stop_not_yet_seen_by_strategy(setup):
    store, _, runner, adapter, version = setup
    runner.em.entry("Long", 1, 1)
    runner.em.process_bar(Bar(4800, 100, 100, 100, 100, 1), runner.bar_index)
    runner.em.close("Long", "L_SL")
    runner.em.process_bar(Bar(4801, 90, 90, 90, 90, 1), runner.bar_index)
    assert runner.strat.bars_since_stop == 999 and runner.strat._prev_closed == 0
    assert store.activate(version["version_id"], "unseen-stop", adapter.boundary)["status"] == "applied"
    assert runner.strat.bars_since_stop == 0 and runner.strat._prev_closed == 1


def test_recovered_feed_fault_keeps_cumulative_count_without_blocking_rollback(setup, monkeypatch):
    store, _, runner, adapter, version = setup
    assert store.activate(version["version_id"], "before-feed-fault", adapter.boundary)["status"] == "applied"
    def fail(*args, **kwargs):
        raise TimeoutError("test timeout")
    monkeypatch.setattr(runner.feed, "recent_ex", fail)
    runner.poll()
    assert runner.errors == 1 and runner.last_error == runner.feed_error == "test timeout"
    assert store.rollback("NQ", "during-fault", adapter.boundary)["status"] == "rejected"
    monkeypatch.setattr(runner.feed, "recent_ex", lambda *a, **kw: ([], 4800, 100))
    runner.poll()
    assert runner.errors == 1 and runner.feed_error == runner.last_error == ""
    assert store.rollback("NQ", "after-fault", adapter.boundary)["status"] == "rolled_back"
    runner.runtime_error = runner.last_error = "strategy error still unresolved"
    runner._feed_failed("another timeout")
    runner.poll()
    assert runner.errors == 2 and runner.last_error == "strategy error still unresolved"


def test_failed_commit_restores_exact_runner_references_and_points(setup, monkeypatch):
    store, _, runner, adapter, version = setup
    actual_history(runner)
    before = dict(runner.__dict__)
    cfg = asdict(runner.cfg)
    finish = store._finish
    calls = []
    def fail_once(operation, active):
        calls.append(1)
        if len(calls) == 1: raise OSError("injected durable commit failure")
        return finish(operation, active)
    monkeypatch.setattr(store, "_finish", fail_once)
    operation = store.activate(version["version_id"], "fail", adapter.boundary)
    assert operation["status"] == "failed" and store.active_profile("NQ") is None
    assert set(runner.__dict__) == set(before)
    assert all(runner.__dict__[name] is value for name, value in before.items())
    assert asdict(runner.cfg) == cfg


@pytest.mark.parametrize("kind", ["entry", "open", "close", "exit"])
def test_shadow_exposure_is_rejected_without_fake_live_fills(setup, monkeypatch, kind):
    store, _, runner, adapter, version = setup
    before = runner.cfg, runner.strat, runner.em, list(runner.em.fills), runner.live_from_ts
    original = AssetRunner.rewarm
    def exposed(shadow, *args, **kwargs):
        original(shadow, *args, **kwargs)
        assert shadow.journal is not runner.journal
        if kind in ("entry", "open"):
            shadow.em.entry("shadow", 1, 1)
        if kind == "open":
            shadow.em.process_bar(Bar(5000, 100, 100, 100, 100, 1), shadow.bar_index + 1)
        if kind == "close": shadow.em._pending_closes.append(PendingClose("shadow", "orphan close", 1))
        if kind == "exit": shadow.em.exit("orphan", "shadow", stop=90)
    monkeypatch.setattr(AssetRunner, "rewarm", exposed)
    operation = store.activate(version["version_id"], "shadow-" + kind, adapter.boundary)
    assert operation["status"] == "failed" and "shadow replay" in operation["error"]
    assert (runner.cfg, runner.strat, runner.em, list(runner.em.fills), runner.live_from_ts) == before
    assert not runner.em.open and not runner.em._pending_entries


@pytest.mark.parametrize("gate", ["warm", "open", "pending", "exits", "error", "approval", "fingerprint", "htf"])
def test_closed_local_gates_do_not_mutate_configuration(setup, gate):
    store, _, runner, adapter, version = setup
    if gate == "warm": runner.warm = False
    if gate in ("open", "pending"):
        runner.em.entry("actual", 1, 1)
        if gate == "open": runner.em.process_bar(Bar(5000, 100, 100, 100, 100, 1), runner.bar_index + 1)
    if gate == "exits": runner.em.exit("orphan", "actual", stop=90)
    if gate == "error": runner.last_error = "unresolved feed failure"
    if gate == "approval": adapter.verify_artifact = lambda _: None
    if gate == "fingerprint": adapter.fingerprint = lambda *_: (None, "f"*64, "a"*64, {})
    if gate == "htf":
        approved = deepcopy(version["artifact"])
        approved["candidate"]["inputs"] = {"htf_tf_1": "3D"}
        approved["candidate_hash"] = canonical_hash(approved["candidate"])
        for review in approved["reviews"]: review["candidate_hash"] = approved["candidate_hash"]
        adapter.verify_artifact = lambda _: approved
        version = store.register(approved)
    cfg, strategy = runner.cfg, runner.strat
    operation = store.activate(version["version_id"], "gate-" + gate, adapter.boundary)
    assert operation["status"] == "rejected", operation
    assert runner.cfg is cfg and runner.strat is strategy and store.active_profile("NQ") is None


def test_callbacks_run_under_port_and_sorted_runner_locks(setup):
    store, port, runner, adapter, version = setup
    def verify(value):
        assert port._lock._is_owned()
        assert all(r.lock._is_owned() for r in port.runners.values())
        return value
    adapter.verify_artifact = verify
    assert store.activate(version["version_id"], "locks", adapter.boundary)["status"] == "applied"


def test_restart_loads_overlay_without_replacing_startup_accounting(setup, tmp_path):
    store, _, _, adapter, version = setup
    assert store.activate(version["version_id"], "apply", adapter.boundary)["status"] == "applied"
    restarted, runner = make_port(tmp_path)
    try:
        runner.cfg.scale_known_at = 99999  # A receipt timestamp alone is not an owner-input change.
        accounting = actual_history(runner)
        assert load_startup_overlay(restarted, runner)
        assert runner.inputs_base.conf_min_votes == 9
        assert (runner.em, runner.em.closed, runner.em.fills, runner.em.netprofit, runner.em._seq) == accounting
        assert runner.live_from_ts == 5000 and not runner._activation_quarantine
    finally:
        restarted.journal.con.close()


@pytest.mark.parametrize("change", ["owner", "unrelated_owner", "scale", "pending_operation", "open_position"])
def test_restart_quarantines_changed_or_incomplete_overlay(setup, tmp_path, change):
    store, _, _, adapter, version = setup
    assert store.activate(version["version_id"], "apply", adapter.boundary)["status"] == "applied"
    if change in ("owner", "unrelated_owner"):
        path = tmp_path / ("inputs.NQ.json" if change == "owner" else "inputs.ES.json")
        path.write_text('{"conf_min_votes":10}')
    if change == "pending_operation":
        with store._connect() as con:
            previous = store._read(con.execute("SELECT * FROM activation_operations WHERE operation_id='apply'").fetchone())
            previous.update(operation_id="interrupted", status="prepared")
            store._save_operation(con, previous)
    restarted, runner = make_port(tmp_path)
    try:
        if change == "scale": runner.cfg.pts_ref_price = 900
        if change == "open_position":
            runner.em.entry("actual", 1, 1)
            runner.em.process_bar(Bar(5000, 100, 100, 100, 100, 1), runner.bar_index + 1)
        assert not load_startup_overlay(restarted, runner)
        assert runner.inputs_base.conf_min_votes == 8 and runner.paused and runner._activation_quarantine
        with pytest.raises(ValueError, match="recovery"):
            runner.set_paused(False)
        with pytest.raises(ValueError, match="recover"):
            runner.ensure_configurable()
    finally:
        restarted.journal.con.close()


def test_startup_hook_runs_before_first_poll(tmp_path, monkeypatch):
    port, runner = make_port(tmp_path)
    calls = []
    monkeypatch.setattr(runner, "warmup", lambda: calls.append("warmup"))
    def startup(actual_port, actual_runner):
        assert (actual_port, actual_runner) == (port, runner)
        calls.append("overlay")
    monkeypatch.setattr("icarus_engine.activation_runtime.load_startup_overlay", startup)
    def poll(): calls.append("poll"); port._stop.set()
    monkeypatch.setattr(runner, "poll", poll)
    try:
        port._run(runner)
        assert calls == ["warmup", "overlay", "poll"]
    finally:
        port.journal.con.close()
