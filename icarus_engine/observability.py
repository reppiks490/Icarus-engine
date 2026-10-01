"""Behavior-neutral decision, replay and provider observability for ICARUS."""
from __future__ import annotations
import json, os, tempfile, time
from collections import deque
from typing import Any, Dict, Iterable, Optional

def explain_decision(state: Dict[str,Any]) -> Dict[str,Any]:
    if not state:
        return {"status":"NO_STATE","blockers":[],"execution_authorized":False}
    blockers=[]
    if state.get("in_session") is False: blockers.append("OUTSIDE_SESSION")
    if state.get("entry_allowed") is False: blockers.append("ENTRY_DISABLED")
    if state.get("diverge_veto_l"): blockers.append("LONG_DIVERGENCE_VETO")
    if state.get("diverge_veto_s"): blockers.append("SHORT_DIVERGENCE_VETO")
    if state.get("gate_long") is False: blockers.append("LONG_GATE")
    if state.get("gate_short") is False: blockers.append("SHORT_GATE")
    fl=float(state.get("final_l") or 0); fs=float(state.get("final_s") or 0); th=float(state.get("eff_thresh") or 0)
    return {"status":"CLEAR" if not blockers else "BLOCKED","blockers":blockers,
            "long_score":fl,"short_score":fs,"threshold":th,
            "long_distance":th-fl,"short_distance":th-fs,"execution_authorized":False}

class CounterfactualTracker:
    """Score blocked threshold-crossing signals at future closes without creating orders."""
    def __init__(self,horizons=(1,3,6),max_candidates=1000):
        self.horizons=tuple(sorted(set(int(x) for x in horizons if int(x)>0)))
        self.max_candidates=max_candidates; self.bar=0; self.pending=deque(); self.done=deque(maxlen=max_candidates)
        self._last_candidate={"long":-10**9,"short":-10**9}
    def observe(self,ts:int,close:float,state:Dict[str,Any]):
        self.bar+=1
        for p in list(self.pending):
            age=self.bar-p["bar"]
            if age in self.horizons and age not in p["outcomes"]:
                raw=(close/p["price"]-1.0)*(1 if p["direction"]=="long" else -1)
                p["outcomes"][age]=raw
            if age>=max(self.horizons):
                self.pending.remove(p); self.done.append(p)
        th=float(state.get("eff_thresh") or 0); allowed=bool(state.get("entry_allowed"))
        for direction,key,gate,veto in (
            ("long","final_l","gate_long","diverge_veto_l"),("short","final_s","gate_short","diverge_veto_s")):
            score=float(state.get(key) or 0)
            blocked=(not allowed) or state.get(gate) is False or bool(state.get(veto))
            if th>0 and score>=th and blocked and self.bar-self._last_candidate[direction]>=max(self.horizons):
                self.pending.append({"ts":int(ts),"bar":self.bar,"direction":direction,"price":float(close),
                                     "score":score,"threshold":th,"reason":explain_decision(state)["blockers"],"outcomes":{}})
                self._last_candidate[direction]=self.bar
        while len(self.pending)>self.max_candidates: self.pending.popleft()
    def view(self):
        by={h:[] for h in self.horizons}
        for p in self.done:
            for h,v in p["outcomes"].items(): by[h].append(v)
        return {"pending":len(self.pending),"completed":len(self.done),
                "horizons":{str(h):{"n":len(v),"mean_directional_return":(sum(v)/len(v) if v else None),
                                    "positive_rate":(sum(x>0 for x in v)/len(v) if v else None)} for h,v in by.items()},
                "mode":"COUNTERFACTUAL_ONLY","execution_authorized":False}

class ProviderHealth:
    def __init__(self,providers:Iterable[str]):
        self.providers={str(p):{"ok":0,"fail":0,"last_ok":None,"last_error":None} for p in providers}
    def ok(self,p):
        x=self.providers.setdefault(str(p),{"ok":0,"fail":0,"last_ok":None,"last_error":None})
        x["ok"]+=1; x["last_ok"]=int(time.time()); x["last_error"]=None
    def fail(self,p,error):
        x=self.providers.setdefault(str(p),{"ok":0,"fail":0,"last_ok":None,"last_error":None})
        x["fail"]+=1; x["last_error"]=str(error)[:300]
    def view(self,primary,secondary=None):
        p=self.providers.get(str(primary),{})
        status="HEALTHY" if p.get("ok",0)>0 and not p.get("last_error") else ("DEGRADED" if p.get("fail",0)>0 else "UNKNOWN")
        return {"status":status,"primary":primary,"secondary":secondary,"providers":self.providers,
                "failover_configured":bool(secondary),"execution_authorized":False}

class ReplayCheckpointLedger:
    """Persistent digest ledger for cross-restart replay equivalence; does not restore executable state."""
    SCHEMA="icarus-replay-ledger-v1"
    def __init__(self,path,max_entries=2000):
        self.path=path; self.max_entries=max_entries; self.entries={}; self.divergences=0; self.last_divergence=None
        try:
            with open(path,encoding="utf-8") as f:
                d=json.load(f)
            if d.get("schema_version")==self.SCHEMA: self.entries=dict(d.get("entries") or {})
        except (OSError,ValueError,TypeError): pass
    def observe(self,ts:int,digest:str):
        k=str(int(ts)); old=self.entries.get(k)
        if old is not None and old!=digest:
            self.divergences+=1; self.last_divergence={"ts":int(ts),"expected":old,"observed":digest}
        self.entries[k]=digest
        if len(self.entries)>self.max_entries:
            for k0 in sorted(self.entries,key=lambda x:int(x))[:len(self.entries)-self.max_entries]: self.entries.pop(k0,None)
        return old is None or old==digest
    def flush(self):
        os.makedirs(os.path.dirname(self.path),exist_ok=True)
        payload={"schema_version":self.SCHEMA,"entries":self.entries,"execution_authorized":False}
        fd,tmp=tempfile.mkstemp(prefix=".replay-",dir=os.path.dirname(self.path),text=True)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(payload,f,sort_keys=True); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def view(self):
        return {"checkpoints":len(self.entries),"divergences_this_run":self.divergences,
                "last_divergence":self.last_divergence,"restore_enabled":False,
                "mode":"EQUIVALENCE_AUDIT_ONLY","execution_authorized":False}


class DecisionTrace:
    """Bounded causal trace from strategy decision -> pending entry -> fill."""
    def __init__(self,maxlen=200):
        self.rows=deque(maxlen=maxlen); self._seen=set()
    def capture(self,ts:int,bar_index:int,pending_entries,decision:Dict[str,Any],digest:Optional[str]):
        for p in pending_entries:
            if getattr(p,"placed_bar",None)!=bar_index: continue
            seq=int(getattr(p,"seq",-1))
            if seq in self._seen: continue
            self._seen.add(seq)
            self.rows.append({"intent_seq":seq,"decision_ts":int(ts),"decision_bar":int(bar_index),
                              "entry_id":str(getattr(p,"id","")),"direction":int(getattr(p,"direction",0)),
                              "qty":int(getattr(p,"qty",0)),"limit":getattr(p,"limit",None),
                              "decision_digest":digest,"decision":decision,"fill":None})
    def record_fill(self,fill):
        if getattr(fill,"kind",None)!="entry": return
        for row in reversed(self.rows):
            if row["fill"] is None and row["entry_id"]==getattr(fill,"entry_id",None):
                row["fill"]={"ts":int(fill.ts),"bar":int(fill.bar),"price":float(fill.price),"qty":int(fill.qty),
                             "side":str(fill.side)}
                break
    def view(self,limit=20):
        rows=list(self.rows)[-max(1,int(limit)):]
        return {"count":len(self.rows),"recent":rows,"mode":"AUDIT_ONLY","execution_authorized":False}
