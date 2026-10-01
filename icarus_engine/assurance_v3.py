"""Behavior-neutral assurance and shadow analytics for ICARUS.

Nothing in this module can submit or modify orders.  It observes bars/state/fills
and produces deterministic evidence for parity, session and execution research.
"""
from __future__ import annotations
import hashlib, json, math
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, Optional

def canonical_digest(payload: Any) -> str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()

@dataclass
class ParitySnapshot:
    ts: int
    digest: str
    fields: int

class ParityMonitor:
    """Digest selected closed-bar state so later replay can be compared exactly."""
    def __init__(self):
        self.latest: Optional[ParitySnapshot]=None
        self.previous: Optional[ParitySnapshot]=None
        self.samples=0
    def observe(self, ts: int, state: Dict[str,Any]):
        safe={k:v for k,v in state.items() if isinstance(v,(type(None),bool,int,float,str,list,dict))}
        # JSON has no portable NaN representation; normalize non-finite values.
        def clean(x):
            if isinstance(x,float) and not math.isfinite(x): return None
            if isinstance(x,list): return [clean(v) for v in x]
            if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
            return x
        safe=clean(safe)
        self.previous=self.latest
        self.latest=ParitySnapshot(int(ts),canonical_digest(safe),len(safe))
        self.samples+=1
        return self.latest
    def view(self):
        return {"samples":self.samples,"latest":asdict(self.latest) if self.latest else None,
                "previous":asdict(self.previous) if self.previous else None,
                "execution_authorized":False}

class SessionShadow:
    """Track observed RTH/ETH returns without changing the strategy's configured session."""
    def __init__(self):
        self.rth_bars=0; self.eth_bars=0; self.unclassified_bars=0
        self.rth_log_return=0.0; self.eth_log_return=0.0
        self._last_rth=None; self._last_eth=None
    def observe(self, close: float, in_rth):
        if in_rth is None:
            self.unclassified_bars+=1
            return
        if in_rth:
            self.rth_bars+=1
            if self._last_rth and close>0 and self._last_rth>0: self.rth_log_return += math.log(close/self._last_rth)
            self._last_rth=close
        else:
            self.eth_bars+=1
            if self._last_eth and close>0 and self._last_eth>0: self.eth_log_return += math.log(close/self._last_eth)
            self._last_eth=close
    def view(self):
        return {"rth_bars":self.rth_bars,"eth_bars":self.eth_bars,"unclassified_bars":self.unclassified_bars,
                "rth_log_return_sum":self.rth_log_return,"eth_log_return_sum":self.eth_log_return,
                "mode":"SHADOW_ONLY","execution_authorized":False}

def execution_stress(trades: Iterable[Dict[str,Any]], *, tick_size: float, multiplier: float,
                     extra_slippage_ticks=(0,1,2,4), extra_commission_per_contract=(0.0,1.0,2.0)):
    """Re-price already-closed trades under worse costs; never changes emulator state."""
    rows=list(trades); out=[]
    base=sum(float(t.get("profit") or 0) for t in rows)
    for slip in extra_slippage_ticks:
        for fee in extra_commission_per_contract:
            penalty=0.0
            for t in rows:
                q=abs(int(t.get("qty") or 0))
                penalty += q*(2.0*slip*tick_size*multiplier + 2.0*fee)
            out.append({"extra_slippage_ticks":slip,"extra_commission_per_contract":fee,
                        "netprofit":base-penalty,"delta":-penalty})
    return {"base_netprofit":base,"scenarios":out,"trades":len(rows),"execution_authorized":False}

def roll_provenance(roller):
    if roller is None: return None
    return {"current":roller.ticker,"next":roller.next_ticker,"expiry":roller.expiry().isoformat(),
            "history":list(roller.history),"rule":"last-completed-session-volume","execution_authorized":False}


def timeframe_integrity(chart_ts, chains, bucket_start):
    """Check that no timeframe chain exposes a completed bucket from the future."""
    if chart_ts is None:
        return {"status":"NO_CHART_BAR","checks":[],"violations":0,"execution_authorized":False}
    checks=[]; violations=0
    for minutes,ch in sorted(chains.items()):
        st=ch.state(); last=st.get("last")
        current_bucket=bucket_start(int(chart_ts),int(minutes))
        future=bool(last is not None and int(last)>int(current_bucket))
        violations+=int(future)
        checks.append({"tf_minutes":int(minutes),"last_completed":last,
                       "current_bucket":int(current_bucket),"future_bucket":future,
                       "bars":st.get("bars")})
    return {"status":"PASS" if not violations else "VIOLATION","checks":checks,
            "violations":violations,"rule":"last_completed <= current_bucket_start",
            "execution_authorized":False}
