"""Execution controls use the real emulator and strategy, without market services."""
import json
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, replace

import pytest

from icarus_engine.assets import AssetSpec
from icarus_engine.pine.timeframe import Bar
from icarus_engine.runtime import AssetRunner, Journal, Portfolio, RunnerConfig
from icarus_engine.server import serve
from icarus_engine.strategy.inputs import Inputs


def make_runner(symbol="TEST"):
    spec = AssetSpec(symbol, symbol, "yahoo", symbol, "crypto", 1, 1,
                     chart_tf="1", commission=0, roll="none")
    r = AssetRunner(RunnerConfig(spec, Inputs(use_tide=False, use_eod_flat=False)), Journal(":memory:"))
    r._init_strategy(100)
    r.last_price = 100
    r.warm = True
    return r


def pending(r, direction=1, limit=None):
    entry = "Long" if direction == 1 else "Short"
    r.em.entry(entry, direction, 1, limit=limit)
    r.em.exit("pending_bracket", entry, stop=90 if direction == 1 else 110)
    r.strat.w_slot_queue.append(1)
    r.strat.tod_hour_queue.append(9)
    if limit is not None:
        r.strat.rate_pend_dir = direction
        r.strat.rate_pend_bar = 0


@pytest.mark.parametrize("limit", [None, 99])
def test_pause_cancels_market_and_limit_before_next_fill(limit):
    r = make_runner()
    r.strat.w_slot_queue = [0]
    r.strat.tod_hour_queue = [8]
    pending(r, limit=limit)
    assert r.set_paused(True) == 1
    assert not r.em._pending_entries and not r.em._exits
    assert r.strat.w_slot_queue == [0] and r.strat.tod_hour_queue == [8]
    assert r.strat.rate_pend_dir == 0
    r.on_sub_bar(Bar(60, 100, 105, 94, 100, 1), 1, live=True)
    assert not r.em.fills


def test_legacy_pause_flag_is_checked_before_emulator_fills():
    r = make_runner()
    pending(r)
    r.paused = True
    r.on_sub_bar(Bar(60, 100, 100, 100, 100, 1), 1, live=True)
    assert not r.em.open and not r.em.fills and not r.em._pending_entries
    assert not r.strat.w_slot_queue


def test_pause_preserves_active_protection_and_closed_trade_learning():
    r = make_runner()
    r.em.entry("Long", 1, 1)
    r.em.process_bar(Bar(0, 100, 100, 100, 100, 1), 0)
    r.em.exit("protect", "Long", stop=95, comment_loss="L_SL")
    r.strat.w_slot_queue = [0]
    r.strat.tod_hour_queue = [8]
    pending(r, -1)
    r.set_paused(True)
    assert "protect" in r.em._exits and "pending_bracket" not in r.em._exits
    assert r.strat.w_slot_queue == [0]
    r.on_sub_bar(Bar(60, 100, 100, 94, 95, 1), 1, live=True)
    assert not r.em.open
    assert r.em.closed[0].exit_comment == "L_SL"
    assert r.strat.w_outcome[0] == -1 and r.strat.tod_losses[8] == 1
    assert not r.strat.w_slot_queue and not r.strat.tod_hour_queue


def test_pause_keeps_close_order_for_open_trade():
    r = make_runner()
    r.em.entry("Long", 1, 1)
    r.em.process_bar(Bar(0, 100, 100, 100, 100, 1), 0)
    r.em.close("Long", "protective close")
    pending(r, -1)
    r.set_paused(True)
    assert [c.entry_id for c in r.em._pending_closes] == ["Long"]
    r.em.process_bar(Bar(60, 100, 100, 100, 100, 1), 1)
    assert not r.em.open and r.em.closed[0].exit_comment == "protective close"


def test_pause_clears_stale_pullback_intent_without_discarding_filled_snapshot():
    r = make_runner()
    pending(r, limit=100)
    r.em.process_bar(Bar(0, 100, 100, 100, 100, 1), 0)
    assert r.strat.rate_pend_dir == 1 and r.em.position_size == 1
    r.set_paused(True)
    assert r.strat.rate_pend_dir == 0
    assert r.strat.w_slot_queue == [1] and r.strat.tod_hour_queue == [9]


def test_flatten_pending_only_cancels_intent_without_a_fill():
    r = make_runner()
    pending(r, limit=99)
    assert r.flatten() == 0
    assert not r.em._pending_entries and not r.em._exits
    assert not r.strat.w_slot_queue and not r.strat.tod_hour_queue
    assert r.strat.rate_pend_dir == 0
    r.em.process_bar(Bar(60, 100, 101, 90, 100, 1), 1)
    assert not r.em.fills


def test_flatten_open_trade_cannot_fill_pending_reversal():
    r = make_runner()
    r.em.entry("Long", 1, 1)
    r.em.process_bar(Bar(0, 100, 100, 100, 100, 1), 0)
    r.strat.w_slot_queue = [0]
    r.strat.tod_hour_queue = [8]
    pending(r, -1)
    assert r.flatten() == 1
    assert not r.em.open and not r.em._pending_entries
    assert [f.kind for f in r.em.fills] == ["entry", "close"]
    assert r.strat.w_slot_queue == [0] and r.strat.tod_hour_queue == [8]


@pytest.fixture
def configured(tmp_path):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "other.json").write_text(json.dumps({"tp1_pts": 51, "_meta": {"capital": 12345}}))
    override = tmp_path / "inputs.TEST.json"
    override.write_text('{"tp1_pts": 23}')
    port = Portfolio(Journal(":memory:"), str(tmp_path))
    r = make_runner()
    port.runners[r.symbol] = r
    port.order = [r.symbol]
    return port, r, override


@pytest.mark.parametrize("exposure", ["open", "pending"])
@pytest.mark.parametrize("operation", ["direct", "inputs", "reset", "preset", "rewarm"])
def test_configuration_rejects_exposure_before_mutating_anything(configured, exposure, operation):
    port, r, path = configured
    pending(r)
    if exposure == "open":
        r.em.process_bar(Bar(0, 100, 100, 100, 100, 1), 0)
    old = (r.em, asdict(r.spec), asdict(r.cfg), r.inputs_base.to_dict(), path.read_bytes())
    with pytest.raises(ValueError, match="flatten"):
        if operation == "direct":
            r.rewarm(replace(r.inputs_base, tp1_pts=77))
        elif operation == "inputs":
            port.rewarm_asset("TEST", {"tp1_pts": 77}, True)
        elif operation == "reset":
            port.rewarm_asset("TEST", reset=True)
        elif operation == "preset":
            port.rewarm_asset("TEST", preset="other")
        else:
            port.rewarm_asset("TEST")
    assert (r.em, asdict(r.spec), asdict(r.cfg), r.inputs_base.to_dict(), path.read_bytes()) == old


def test_unavailable_timeframe_rejects_before_persist(configured):
    port, r, path = configured
    before = path.read_bytes()
    with pytest.raises(ValueError, match="cached history unavailable"):
        port.rewarm_asset("TEST", {"htf_tf_1": "720"}, True)
    assert path.read_bytes() == before and r.inputs_base.htf_tf_1 != "720"


@pytest.mark.parametrize("operation", ["direct", "inputs", "reset", "preset", "rewarm"])
def test_initial_warmup_rejects_configuration_before_mutation_or_feed(configured, monkeypatch, operation):
    port, r, path = configured
    r.warm = False
    r.strat = None
    r.cfg.pts_ref_price = 200
    r.subbars = [(Bar(60, 100, 100, 100, 100, 1), 1)]
    def forbidden(*args, **kwargs):
        pytest.fail("initial warming configuration must not fetch market data")
    monkeypatch.setattr(r.feed, "daily_volume", forbidden)
    before = (r.em, asdict(r.spec), asdict(r.cfg), r.inputs_base.to_dict(), path.read_bytes())
    with pytest.raises(ValueError, match="initial warm-up must finish"):
        if operation == "direct":
            r.rewarm(replace(r.inputs_base, tp1_pts=77))
        elif operation == "inputs":
            port.rewarm_asset("TEST", {"tp1_pts": 77}, True)
        elif operation == "reset":
            port.rewarm_asset("TEST", reset=True)
        elif operation == "preset":
            port.rewarm_asset("TEST", preset="other")
        else:
            port.rewarm_asset("TEST")
    assert (r.em, asdict(r.spec), asdict(r.cfg), r.inputs_base.to_dict(), path.read_bytes()) == before
    assert r.strat is None and r.warm is False and r.rewarming is False


@pytest.mark.parametrize("initialized", [True, False])
def test_rewarm_uses_existing_scale_without_current_feed(configured, monkeypatch, initialized):
    port, r, _ = configured
    if not initialized:
        r.strat = None
    r.cfg.pts_ref_price = 200
    r.pts_scale = .5
    r.subbars = [(Bar(60, 100, 100, 100, 100, 1), 1)]
    def forbidden(*args, **kwargs):
        pytest.fail("configuration replay must not request a current daily reference")
    monkeypatch.setattr(r.feed, "daily_volume", forbidden)
    port.rewarm_asset("TEST", {"tp1_pts": 80})
    assert r.inputs_base.tp1_pts == 80 and r.inputs.tp1_pts == 40
    assert r.cfg.inputs == r.inputs_base and r.cfg.fixed_pts_scale == .5


def test_configuration_lock_keeps_concurrent_fill_in_new_engine(configured, monkeypatch):
    port, r, _ = configured
    attempted = threading.Event()
    filled = threading.Event()
    original_guard = r.ensure_configurable
    workers = []
    def fill():
        attempted.set()
        with r.lock:
            r.em.entry("Long", 1, 1)
            r.em.process_bar(Bar(60, 100, 100, 100, 100, 1), 1)
            filled.set()
    def guard():
        original_guard()
        if not workers:
            worker = threading.Thread(target=fill, daemon=True)
            workers.append(worker)
            worker.start()
            assert attempted.wait(3)
            assert not filled.is_set()
    monkeypatch.setattr(r, "ensure_configurable", guard)
    port.rewarm_asset("TEST", {"tp1_pts": 80}, True)
    workers[0].join(3)
    assert filled.is_set() and r.em.position_size == 1
    assert r.inputs_base.tp1_pts == 80


@pytest.fixture
def admin(configured):
    port, r, path = configured
    srv = serve(port, 0, token="test-token", start=False)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    def post(route, body):
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}" + route,
                                     data=json.dumps(body).encode(), headers={"Authorization": "Bearer test-token"})
        try:
            with urllib.request.urlopen(req, timeout=5) as reply:
                return reply.status, json.load(reply)
        except urllib.error.HTTPError as ex:
            return ex.code, json.load(ex)
    yield port, r, path, post
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def test_all_admin_configuration_routes_reject_pending_before_side_effects(admin):
    _, r, path, post = admin
    pending(r)
    before = (r.em, asdict(r.spec), path.read_bytes())
    for route, extra in [("inputs", {"values": {"tp1_pts": 80}}), ("inputs/reset", {}),
                         ("preset", {"preset": "other"}), ("rewarm", {})]:
        status, body = post("/admin/" + route, {"asset": "TEST", **extra})
        assert status == 400 and "flatten" in body["detail"]
        assert (r.em, asdict(r.spec), path.read_bytes()) == before


def test_admin_all_assets_preflight_prevents_partial_writes(admin):
    port, r, path, post = admin
    other = make_runner("OTHER")
    port.runners["OTHER"] = other
    port.order.append("OTHER")
    pending(other)
    before = path.read_bytes()
    status, _ = post("/admin/inputs", {"asset": "*", "values": {"tp1_pts": 80}})
    assert status == 400
    assert path.read_bytes() == before and r.inputs_base.tp1_pts != 80


def test_admin_pause_flatten_and_config_success_are_completed_on_return(admin):
    _, r, path, post = admin
    pending(r, limit=99)
    assert post("/admin/pause", {"asset": "TEST"})[0] == 200
    assert r.paused and not r.em._pending_entries
    assert post("/admin/preset", {"asset": "TEST", "preset": "other"})[0] == 200
    assert r.cfg.preset == "other" and r.spec.capital == 12345 and not r.rewarming
    assert post("/admin/inputs/reset", {"asset": "TEST"})[0] == 200
    assert not path.exists() and r.inputs_base.tp1_pts == 51
    assert post("/admin/resume", {"asset": "TEST"})[0] == 200
    assert not r.paused
    r._init_strategy(100)
    pending(r)
    status, response = post("/admin/flatten", {"asset": "TEST", "confirm": True})
    assert status == 200 and response["closed"] == {"TEST": 0}
    assert not r.em._pending_entries
