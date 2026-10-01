"""Research-only continuous futures history constructor with explicit roll provenance.

This module never changes the live feed or strategy. It consumes discrete
contract CSVs plus an explicit roll manifest and materializes research artifacts.
"""
from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from .history_v2 import load_csv, write_bars_csv
from .pine.timeframe import Bar

SCHEMA="icarus-continuous-roll-manifest-v1"

def archive_status(base_dir:str,symbol:str):
    root=Path(base_dir)/"history"/"contracts"/str(symbol).upper()
    manifest=root/"rolls.json"
    files=sorted(p.name for p in root.glob("*.csv")) if root.is_dir() else []
    return {"configured":manifest.is_file() and bool(files),"root":os.path.relpath(root,base_dir),
            "manifest":os.path.relpath(manifest,base_dir) if manifest.is_file() else None,
            "contract_files":files,"execution_authorized":False}

def load_manifest(base_dir:str,symbol:str):
    root=Path(base_dir)/"history"/"contracts"/str(symbol).upper()
    p=root/"rolls.json"
    if not p.is_file(): raise ValueError("continuous roll manifest not found")
    d=json.loads(p.read_text(encoding="utf-8"))
    if d.get("schema_version") not in (None,SCHEMA): raise ValueError("unsupported continuous roll manifest schema")
    initial=str(d.get("initial_contract") or "")
    rolls=d.get("rolls") or []
    if not initial or not isinstance(rolls,list): raise ValueError("manifest requires initial_contract and rolls")
    prev_ts=-1; expected=initial
    normalized=[]
    for i,r in enumerate(rolls):
        if not isinstance(r,dict): raise ValueError(f"roll {i}: expected object")
        ts=int(r.get("ts")); frm=str(r.get("from") or ""); to=str(r.get("to") or "")
        if ts<=prev_ts: raise ValueError("roll timestamps must be strictly increasing")
        if frm!=expected: raise ValueError(f"roll chain discontinuity: expected from={expected}, got {frm}")
        if not to or to==frm: raise ValueError("roll target must differ from source")
        normalized.append({"ts":ts,"from":frm,"to":to,"reason":str(r.get("reason") or "explicit_manifest")})
        prev_ts=ts; expected=to
    return root,{"schema_version":SCHEMA,"initial_contract":initial,"rolls":normalized}

def _load_contract(root:Path,name:str,tf_seconds:int):
    p=root/(name+".csv")
    if not p.is_file(): raise ValueError(f"contract file missing: {name}.csv")
    bars,report=load_csv(str(p),tf_seconds,session="CONTRACT")
    if not bars: raise ValueError(f"contract has no valid bars: {name}")
    return bars,report

def _last_before(rows:List[Bar],ts:int):
    x=[b for b in rows if b.ts < ts]
    return x[-1] if x else None

def _first_at_or_after(rows:List[Bar],ts:int):
    return next((b for b in rows if b.ts>=ts),None)

def build_continuous(base_dir:str,symbol:str,tf_minutes:int):
    root,manifest=load_manifest(base_dir,symbol)
    tf_seconds=int(tf_minutes)*60
    names=[manifest["initial_contract"]]+[r["to"] for r in manifest["rolls"]]
    series={}; reports={}
    for name in names:
        if name in series: continue
        bars,rep=_load_contract(root,name,tf_seconds); series[name]=bars; reports[name]=rep.to_dict()

    # Raw splice: old contract strictly before roll timestamp, new at/after.
    intervals=[]
    start=-10**30; active=manifest["initial_contract"]
    for r in manifest["rolls"]:
        intervals.append((start,r["ts"],active)); start=r["ts"]; active=r["to"]
    intervals.append((start,10**30,active))
    raw=[]
    for a,b,name in intervals:
        raw.extend(x for x in series[name] if a<=x.ts<b)
    by_ts={x.ts:x for x in raw}; raw=[by_ts[k] for k in sorted(by_ts)]

    # Difference back-adjust: older segments receive cumulative new-old gaps,
    # preserving each contract's within-segment returns while removing roll gaps.
    roll_diag=[]; adjustments={}
    cumulative=0.0
    for r in reversed(manifest["rolls"]):
        old=_last_before(series[r["from"]],r["ts"]); new=_first_at_or_after(series[r["to"]],r["ts"])
        if old is None or new is None:
            raise ValueError(f"cannot calculate roll gap at {r['ts']} for {r['from']}->{r['to']}")
        gap=float(new.o-old.c)
        cumulative+=gap
        adjustments[r["from"]]=cumulative
        roll_diag.append({"ts":r["ts"],"from":r["from"],"to":r["to"],
                          "old_close":old.c,"new_open":new.o,"gap":gap})
    roll_diag.reverse()
    adjusted=[]
    # Map raw timestamp back to active interval/contract and shift older pieces.
    for a,b,name in intervals:
        shift=adjustments.get(name,0.0)
        for x in series[name]:
            if a<=x.ts<b:
                adjusted.append(Bar(x.ts,x.o+shift,x.h+shift,x.l+shift,x.c+shift,x.v))
    aa={x.ts:x for x in adjusted}; adjusted=[aa[k] for k in sorted(aa)]

    return raw,adjusted,{"schema_version":"icarus-continuous-build-v1","symbol":str(symbol).upper(),
                         "tf_minutes":int(tf_minutes),"manifest":manifest,"contracts":reports,
                         "roll_diagnostics":roll_diag,"raw_bars":len(raw),"adjusted_bars":len(adjusted),
                         "adjustment":"DIFFERENCE_BACK_ADJUST_RESEARCH_ONLY",
                         "execution_authorized":False}

def materialize(base_dir:str,symbol:str,tf_minutes:int):
    raw,adj,meta=build_continuous(base_dir,symbol,tf_minutes)
    out=Path(base_dir)/"state"/"history"/"continuous"/str(symbol).upper()
    out.mkdir(parents=True,exist_ok=True)
    raw_path=out/f"{int(tf_minutes)}m_raw.csv"
    adj_path=out/f"{int(tf_minutes)}m_back_adjusted.csv"
    write_bars_csv(str(raw_path),raw); write_bars_csv(str(adj_path),adj)
    meta_path=out/f"{int(tf_minutes)}m_manifest.json"
    meta_path.write_text(json.dumps(meta,indent=2,sort_keys=True),encoding="utf-8")
    return {"raw_path":os.path.relpath(raw_path,base_dir),
            "adjusted_path":os.path.relpath(adj_path,base_dir),
            "manifest_path":os.path.relpath(meta_path,base_dir),
            "meta":meta,"execution_authorized":False}
