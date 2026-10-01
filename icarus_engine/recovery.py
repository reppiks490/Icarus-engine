"""Deterministic restart-recovery witness for ICARUS.

The engine recovers by replaying persisted market bars, not by deserializing
executable strategy/order objects. This witness records the last closed-bar
decision/broker snapshot and verifies that a later replay reconstructs it.
"""
from __future__ import annotations
import json, os, tempfile, time
from typing import Any, Dict

SCHEMA="icarus-recovery-witness-v1"

def _trade_sig(t):
    return {"id":str(getattr(t,"entry_id","")),"direction":int(getattr(t,"direction",0)),
            "qty":int(getattr(t,"qty",0)),"entry_price":float(getattr(t,"entry_price",0.0)),
            "entry_ts":int(getattr(t,"entry_ts",0))}

def _pending_sig(p):
    return {"id":str(getattr(p,"id","")),"direction":int(getattr(p,"direction",0)),
            "qty":int(getattr(p,"qty",0)),"limit":getattr(p,"limit",None),
            "placed_bar":int(getattr(p,"placed_bar",-1))}

def snapshot(ts:int,digest:str,em) -> Dict[str,Any]:
    return {"bar_ts":int(ts),"decision_digest":str(digest),
            "position_size":int(em.position_size),
            "open_trades":[_trade_sig(t) for t in em.open],
            "pending_entries":[_pending_sig(p) for p in em._pending_entries],
            "execution_authorized":False}

def compare(expected:Dict[str,Any],observed:Dict[str,Any]):
    fields=("decision_digest","position_size","open_trades","pending_entries")
    diff={k:{"expected":expected.get(k),"observed":observed.get(k)}
          for k in fields if expected.get(k)!=observed.get(k)}
    return {"status":"MATCH" if not diff else "DIVERGENCE","bar_ts":observed.get("bar_ts"),
            "differences":diff,"method":"DETERMINISTIC_REPLAY_NOT_STATE_RESTORE",
            "execution_authorized":False}

class RecoveryWitness:
    def __init__(self,path:str):
        self.path=os.path.realpath(path); self.prior=None; self.check=None; self.current=None
        try:
            with open(self.path,encoding="utf-8") as f: d=json.load(f)
            if d.get("schema_version")==SCHEMA and d.get("execution_authorized") is False:
                self.prior=d.get("snapshot")
        except (OSError,ValueError,TypeError): pass

    def observe_replay(self,ts:int,digest:str,em):
        if not self.prior or self.check is not None: return
        target=int(self.prior.get("bar_ts") or -1)
        if int(ts)<target: return
        if int(ts)>target:
            self.check={"status":"REFERENCE_BAR_MISSING","expected_bar_ts":target,"observed_bar_ts":int(ts),
                        "method":"DETERMINISTIC_REPLAY_NOT_STATE_RESTORE","execution_authorized":False}
            return
        self.check=compare(self.prior,snapshot(ts,digest,em))

    def write_live(self,ts:int,digest:str,em):
        self.current=snapshot(ts,digest,em)
        payload={"schema_version":SCHEMA,"saved_at":int(time.time()),"snapshot":self.current,
                 "execution_authorized":False}
        os.makedirs(os.path.dirname(self.path),exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=".recovery-",dir=os.path.dirname(self.path),text=True)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                json.dump(payload,f,sort_keys=True); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def view(self):
        if self.prior is None:
            status="NO_PRIOR_WITNESS"
        elif self.check is None:
            status="AWAITING_REFERENCE_BAR"
        else:
            status=self.check.get("status","UNKNOWN")
        return {"status":status,"prior":self.prior,"check":self.check,
                "current":self.current,"recovery_method":"DETERMINISTIC_MARKET_REPLAY",
                "state_restore_enabled":False,"execution_authorized":False}
