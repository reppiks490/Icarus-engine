from icarus_engine.assurance_v3 import ParityMonitor, SessionShadow, execution_stress, roll_provenance
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
