from icarus_engine.observability import explain_decision, CounterfactualTracker, ProviderHealth, ReplayCheckpointLedger

def test_decision_explainer_reports_blockers_and_distance():
    v=explain_decision({"in_session":False,"entry_allowed":False,"gate_long":False,"gate_short":True,
                        "final_l":1.0,"final_s":0.2,"eff_thresh":1.2})
    assert v["status"]=="BLOCKED" and "OUTSIDE_SESSION" in v["blockers"] and v["long_distance"]==.2
    assert v["execution_authorized"] is False

def test_counterfactual_scores_without_orders():
    c=CounterfactualTracker(horizons=(1,2))
    blocked={"entry_allowed":False,"gate_long":False,"gate_short":True,"diverge_veto_l":False,"diverge_veto_s":False,
             "final_l":2,"final_s":0,"eff_thresh":1}
    c.observe(1,100,blocked); c.observe(2,101,{}); c.observe(3,102,{})
    v=c.view(); assert v["completed"]==1 and v["horizons"]["2"]["mean_directional_return"]>0
    assert v["mode"]=="COUNTERFACTUAL_ONLY"

def test_provider_health_tracks_failover_status():
    h=ProviderHealth(["coinbase","kraken"]); h.fail("coinbase","x"); h.ok("kraken")
    v=h.view("coinbase","kraken"); assert v["failover_configured"] and v["providers"]["kraken"]["ok"]==1

def test_replay_ledger_detects_cross_run_divergence(tmp_path):
    p=tmp_path/"state"/"r.json"; a=ReplayCheckpointLedger(str(p)); assert a.observe(10,"abc"); a.flush()
    b=ReplayCheckpointLedger(str(p)); assert not b.observe(10,"def"); assert b.view()["divergences_this_run"]==1
    assert b.view()["restore_enabled"] is False
