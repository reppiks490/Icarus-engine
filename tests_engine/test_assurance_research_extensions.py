import time
from pathlib import Path
from types import SimpleNamespace

from icarus_engine import comparison_jobs
from icarus_engine.research_extensions import trade_breakdown, robustness_value, regression_digest


def _summary(net=100.0, trades=2, dd=10.0):
    keys=("total_trades","net_profit","net_profit_pct","percent_profitable","profit_factor",
          "max_drawdown","max_drawdown_pct","expectancy","sharpe","sortino","cagr_pct")
    s={k:{"all":0.0} for k in keys}
    s["total_trades"]={"all":trades}
    s["net_profit"]={"all":net}
    s["max_drawdown"]={"all":dd}
    s["profit_factor"]={"all":2.0}
    s["expectancy"]={"all":net/trades if trades else None}
    return s


def _result(net=100.0,trades=2,dd=10.0):
    rows=[{"type":"long","entry_ts":100+i,"entry_px":100,"exit_ts":200+i,"exit_px":101,
           "exit_signal":"x","qty":1,"pnl":net/max(1,trades),"open":False} for i in range(trades)]
    return {"asset":"NQ","bars":100,"range":{"start":1,"end":2},
            "config":{"session":"rth","chart_type":"real","fill_on":"real","tf":20,"pts_scale":1,
                      "historical_scale_asof_valid":True,"reproducibility":{"subbars_scope":"raw_pre_session_filter","subbars_sha256":"abc"}},
            "summary":_summary(net,trades,dd),"trades":rows,"equity":[],"drawdown":[]}


def test_trade_breakdown_is_descriptive():
    rows=[
        SimpleNamespace(direction=1,entry_ts=1760000000,bars=2,profit=100,runup=150,drawdown=-25),
        SimpleNamespace(direction=-1,entry_ts=1760003600,bars=12,profit=-50,runup=20,drawdown=-90),
    ]
    r=trade_breakdown(rows)
    assert r["overall"]["n"]==2
    assert r["direction"]["long"]["net"]==100
    assert r["holding_bars"]["11-30"]["n"]==1
    assert r["interpretation"]=="DESCRIPTIVE_ONLY"
    assert r["execution_authorized"] is False


def test_robustness_value_and_regression_digest_are_deterministic():
    assert robustness_value(10,0.10,-1)==9
    assert robustness_value(10.0,0.10,1)==11.0
    a=_result(); b=_result()
    assert regression_digest(a)==regression_digest(b)


def test_determinism_job_reports_match(monkeypatch):
    runner=SimpleNamespace(warm=True)
    port=SimpleNamespace(runners={"NQ":runner})
    monkeypatch.setattr(comparison_jobs,"freeze_replay_port",lambda p,s:p)
    monkeypatch.setattr(comparison_jobs,"run_backtest",lambda p,s,**kw:_result())
    jid=comparison_jobs.start_determinism(port,"NQ")
    for _ in range(100):
        j=comparison_jobs.get_job(jid)
        if j["status"]!="running": break
        time.sleep(.01)
    assert j["status"]=="done"
    assert j["result"]["equal"] is True
    assert j["result"]["execution_authorized"] is False


def test_robustness_job_is_local_descriptive_and_non_activating(monkeypatch):
    inputs={"rate_min_mult":2.0,"rate_max_mult":5.0,"shock_z_thresh":2.5,"pe_thresh":0.75,
            "family_discount":0.90,"pulse_conf_weight":0.60}
    runner=SimpleNamespace(warm=True,inputs_base=SimpleNamespace(to_dict=lambda:dict(inputs)))
    port=SimpleNamespace(runners={"NQ":runner})
    monkeypatch.setattr(comparison_jobs,"freeze_replay_port",lambda p,s:p)
    def fake(_p,_s,inputs=None,**kw):
        bump=sum(float(v) for v in (inputs or {}).values()) if inputs else 0
        return _result(net=100+bump,dd=10+bump/10)
    monkeypatch.setattr(comparison_jobs,"run_backtest",fake)
    jid=comparison_jobs.start_robustness(port,"NQ",fields=["rate_min_mult"],fraction=.1)
    for _ in range(100):
        j=comparison_jobs.get_job(jid)
        if j["status"]!="running": break
        time.sleep(.01)
    assert j["status"]=="done"
    assert len(j["result"]["variants"])==2
    assert j["result"]["interpretation"]=="DESCRIPTIVE_LOCAL_SENSITIVITY"
    assert "rank" not in j["result"] and "winner" not in j["result"]
    assert j["result"]["execution_authorized"] is False


def test_assurance_research_ui_is_wired_and_has_no_order_mutation():
    ui=Path("icarus_engine/assurance-ui.js").read_text(encoding="utf-8")
    dash=Path("icarus_engine/dashboard.html").read_text(encoding="utf-8")
    server=Path("icarus_engine/server.py").read_text(encoding="utf-8")
    assert '<script src="/assurance-ui.js"></script>' in dash
    assert 'p.path == "/assurance-ui.js"' in server
    for route in ("/admin/research/determinism","/admin/research/robustness","/admin/research/regression"):
        assert route in server and route in ui
    for forbidden in ("/admin/flatten","/admin/resume","/admin/inputs","/admin/preset","/admin/assets/"):
        assert forbidden not in ui
    assert "never activate parameters, submit orders, or authorize execution" in ui


def test_live_replay_parity_job_matches_frozen_terminal_digest(monkeypatch):
    runner=SimpleNamespace(warm=True,warmup_quality_gate={"status":"READY","reasons":[]})
    frozen_runner=SimpleNamespace(frozen_terminal_bar_ts=123,frozen_terminal_digest="abc")
    frozen=SimpleNamespace(runners={"NQ":frozen_runner})
    port=SimpleNamespace(runners={"NQ":runner})
    monkeypatch.setattr(comparison_jobs,"freeze_replay_port",lambda p,s:frozen)
    monkeypatch.setattr(comparison_jobs,"run_backtest",lambda p,s,**kw:{
        **_result(), "assurance":{"terminal_bar_ts":123,"terminal_decision_digest":"abc","execution_authorized":False}})
    jid=comparison_jobs.start_live_replay_parity(port,"NQ")
    for _ in range(100):
        j=comparison_jobs.get_job(jid)
        if j["status"]!="running": break
        time.sleep(.01)
    assert j["status"]=="done"
    assert j["result"]["status"]=="MATCH"
    assert j["result"]["mode"]=="LIVE_VS_REPLAY_PARITY_AUDIT"
    assert j["result"]["execution_authorized"] is False


def test_backtest_and_ui_expose_terminal_parity_surfaces():
    bt=Path("icarus_engine/backtest.py").read_text(encoding="utf-8")
    ui=Path("icarus_engine/assurance-ui.js").read_text(encoding="utf-8")
    server=Path("icarus_engine/server.py").read_text(encoding="utf-8")
    assert '"terminal_decision_digest"' in bt and "frozen_terminal_digest" in bt
    assert "/admin/research/live-replay-parity" in server
    assert "/api/research/live-replay-parity/" in server
    assert 'data-assurance-job="live-replay-parity"' in ui
