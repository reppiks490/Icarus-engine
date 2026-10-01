import time
from types import SimpleNamespace
from icarus_engine import regression_jobs

def fake_result(net=100.0, trades=2):
    rows=[]
    for i in range(trades):
        rows.append({"type":"long","entry_ts":10+i,"entry_px":100+i,"exit_ts":20+i,"exit_px":101+i,
                     "exit_signal":"X","qty":1,"pnl":net/trades,"open":False})
    summary={k:{"all":0} for k in regression_jobs._METRICS}
    summary["total_trades"]={"all":trades}; summary["net_profit"]={"all":net}
    summary["max_drawdown"]={"all":10}; summary["profit_factor"]={"all":2}
    return {"asset":"NQ","bars":100,"range":{"start":1,"end":2},
            "config":{"preset":"x","fill_on":"real","chart_type":"real","session":"rth","tf":20,
                      "slippage_ticks":2,"commission":2,"pts_scale":1,
                      "reproducibility":{"subbars_sha256":"abc"}},
            "summary":summary,"trades":rows,"equity":[],"drawdown":[]}

def test_regression_snapshot_and_diff_are_descriptive():
    a=regression_jobs.snapshot(fake_result(100,2)); b=regression_jobs.snapshot(fake_result(120,3))
    d=regression_jobs.compare(a,b)
    assert not d["digest_equal"] and d["metrics_delta"]["net_profit"]==20
    assert d["trades_added"]>0 and d["execution_authorized"] is False

def test_baseline_store_roundtrip(tmp_path):
    s=regression_jobs.snapshot(fake_result())
    regression_jobs.save_baseline(tmp_path,"NQ",s)
    got=regression_jobs.load_baseline(tmp_path,"NQ")
    assert got["digest"]==s["digest"] and got["execution_authorized"] is False

def test_async_regression_baseline_and_check(monkeypatch,tmp_path):
    runner=SimpleNamespace(warm=True)
    port=SimpleNamespace(runners={"NQ":runner},base_dir=str(tmp_path))
    monkeypatch.setattr(regression_jobs,"freeze_replay_port",lambda p,s:p)
    monkeypatch.setattr(regression_jobs,"run_backtest",lambda p,s,fill_on=None:fake_result())
    j1=regression_jobs.start(port,"NQ","baseline")
    for _ in range(100):
        a=regression_jobs.get(j1)
        if a["status"]!="running": break
        time.sleep(.01)
    assert a["status"]=="done" and a["result"]["status"]=="BASELINE_SAVED"
    j2=regression_jobs.start(port,"NQ","check")
    for _ in range(100):
        b=regression_jobs.get(j2)
        if b["status"]!="running": break
        time.sleep(.01)
    assert b["result"]["status"]=="COMPARED" and b["result"]["diff"]["digest_equal"]


def test_regression_reports_source_and_config_compatibility():
    a=regression_jobs.snapshot(fake_result())
    changed=fake_result()
    changed["config"]["session"]="eth"
    changed["config"]["reproducibility"]["subbars_sha256"]="different"
    b=regression_jobs.snapshot(changed)
    d=regression_jobs.compare(a,b)
    assert d["config_equal"] is False and "session" in d["config_changes"]
    assert d["source_equal"] is False and "subbars_sha256" in d["source_changes"]

def test_invalid_history_refuses_regression(tmp_path):
    import pytest
    runner=SimpleNamespace(warm=True,warmup_quality_gate={"status":"INVALID","reasons":["NO_VALID_BARS"]})
    port=SimpleNamespace(runners={"NQ":runner},base_dir=str(tmp_path))
    with pytest.raises(ValueError,match="history quality is INVALID"):
        regression_jobs.start(port,"NQ","check")
