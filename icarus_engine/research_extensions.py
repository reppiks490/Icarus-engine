"""Descriptive research analytics for ICARUS. No selection, ranking or order authority."""
from __future__ import annotations
import hashlib, json, math
from datetime import datetime
from zoneinfo import ZoneInfo

_CT=ZoneInfo("America/Chicago")

def _get(x,name,default=None):
    return x.get(name,default) if isinstance(x,dict) else getattr(x,name,default)

def _stats(rows):
    pnl=[float(_get(x,"profit",_get(x,"pnl",0.0)) or 0.0) for x in rows]
    gp=sum(x for x in pnl if x>0); gl=-sum(x for x in pnl if x<0)
    return {"n":len(rows),"net":sum(pnl),"mean":(sum(pnl)/len(pnl) if pnl else None),
            "win_rate":(sum(x>0 for x in pnl)/len(pnl) if pnl else None),
            "profit_factor":(gp/gl if gl else None),
            "avg_runup":(sum(float(_get(x,"runup",0.0) or 0.0) for x in rows)/len(rows) if rows else None),
            "avg_drawdown":(sum(float(_get(x,"drawdown",0.0) or 0.0) for x in rows)/len(rows) if rows else None)}

def trade_breakdown(trades, limit=1000):
    """Describe closed trades by direction, time, duration and exit cause."""
    rows=list(trades)[-max(1,int(limit)):]
    dirs={"long":[],"short":[]}; hours={}; holds={"1-3":[],"4-10":[],"11-30":[],"31+":[]}; exits={}
    for t in rows:
        d="long" if int(_get(t,"direction",1) or 1)>0 else "short"; dirs[d].append(t)
        ts=int(_get(t,"entry_ts",0) or 0)
        if ts:
            h=datetime.fromtimestamp(ts,_CT).hour; hours.setdefault(f"{h:02d}:00",[]).append(t)
        b=int(_get(t,"bars",0) or 0)+1
        k="1-3" if b<=3 else "4-10" if b<=10 else "11-30" if b<=30 else "31+"
        holds[k].append(t)
        reason=str(_get(t,"exit_comment","") or _get(t,"exit_kind","") or "UNSPECIFIED")
        exits.setdefault(reason,[]).append(t)
    return {"overall":_stats(rows),"direction":{k:_stats(v) for k,v in dirs.items()},
            "entry_hour_ct":{k:_stats(v) for k,v in sorted(hours.items())},
            "holding_bars":{k:_stats(v) for k,v in holds.items()},
            "exit_reason":{k:_stats(v) for k,v in sorted(exits.items())},
            "sample_scope":"MOST_RECENT_CLOSED_TRADES","sample_limit":limit,
            "interpretation":"DESCRIPTIVE_ONLY","execution_authorized":False}

def regression_digest(result):
    """Digest stable replay outputs; excludes asynchronous job metadata and CSV formatting."""
    payload={"asset":result.get("asset"),"bars":result.get("bars"),"config":result.get("config"),
             "range":result.get("range"),"summary":result.get("summary"),"trades":result.get("trades"),
             "equity":result.get("equity"),"drawdown":result.get("drawdown")}
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False,default=str).encode()
    return hashlib.sha256(raw).hexdigest()

def robustness_value(center, frac, direction):
    if isinstance(center,bool) or not isinstance(center,(int,float)): raise ValueError("numeric parameter required")
    if isinstance(center,int):
        step=max(1,int(round(abs(center)*frac)))
        return max(0,center+direction*step)
    value=float(center)*(1.0+direction*frac)
    if not math.isfinite(value): raise ValueError("non-finite perturbation")
    return value
