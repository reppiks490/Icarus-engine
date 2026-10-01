from icarus_engine.assurance_v3 import ParityMonitor, SessionShadow, execution_stress, roll_provenance, timeframe_integrity
from icarus_engine.contracts import ContractRoll
from datetime import date

def test_parity_digest_is_deterministic_and_non_authoritative():
    a=ParityMonitor(); b=ParityMonitor()
    x=a.observe(10,{"b":2,"a":1}); y=b.observe(10,{"a":1,"b":2})
    assert x.digest==y.digest and a.view()["execution_authorized"] is False

def test_session_shadow_is_observational():
    s=SessionShadow(); s.observe(100,True); s.observe(101,True); s.observe(99,False); s.observe(100,False)
    v=s.view(); assert v["rth_bars"]==2 and v["eth_bars"]==2 and v["mode"]=="SHADOW_ONLY"

def test_execution_stress_only_degrades_closed_trade_result():
    r=execution_stress([{"profit":100,"qty":2}],tick_size=.25,multiplier=20,
                       extra_slippage_ticks=(0,2),extra_commission_per_contract=(0,1))
    assert r["base_netprofit"]==100
    assert all(x["netprofit"]<=100 for x in r["scenarios"])
    assert r["execution_authorized"] is False

def test_roll_provenance_is_explicit():
    r=ContractRoll("NQ",date(2026,10,1)); v=roll_provenance(r)
    assert v["current"].startswith("NQ") and v["next"].startswith("NQ")
    assert v["rule"]=="last-completed-session-volume" and v["execution_authorized"] is False

def test_runtime_wires_assurance_without_order_authority():
    from pathlib import Path
    text=Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    for token in ("ParityMonitor()","SessionShadow()","parity_monitor.observe","execution_stress(","roll_provenance("):
        assert token in text
    mod=Path("icarus_engine/assurance_v3.py").read_text(encoding="utf-8")
    assert ".entry(" not in mod and ".exit(" not in mod and ".close(" not in mod

def test_dashboard_labels_assurance_shadow_only():
    from pathlib import Path
    text=Path("icarus_engine/dashboard.html").read_text(encoding="utf-8")
    assert "Assurance · shadow only" in text
    assert "cannot submit or modify orders" in text


def test_timeframe_integrity_flags_future_completed_bucket():
    class C:
        def __init__(self,last): self.last=last
        def state(self): return {"last":self.last,"bars":10}
    bucket=lambda ts,m: ts-(ts%(m*60))
    ok=timeframe_integrity(3600,{5:C(3300),60:C(0)},bucket)
    bad=timeframe_integrity(3600,{5:C(3900)},bucket)
    assert ok["status"]=="PASS" and ok["violations"]==0
    assert bad["status"]=="VIOLATION" and bad["violations"]==1
    assert bad["execution_authorized"] is False

def test_runtime_and_ui_surface_timeframe_integrity():
    from pathlib import Path
    rt=Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    ui=Path("icarus_engine/assurance-ui.js").read_text(encoding="utf-8")
    assert '"timeframe_integrity"' in rt
    assert "Multi-timeframe temporal integrity" in ui
