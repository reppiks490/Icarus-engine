"""Deterministic session-specific historical fragment discovery and stitching."""
from __future__ import annotations
import csv, json, os, tempfile
from pathlib import Path
from .history_v2 import load_csv
from .pine.timeframe import Bar

def _same(a:Bar,b:Bar)->bool:
    return (a.o,a.h,a.l,a.c,a.v)==(b.o,b.h,b.l,b.c,b.v)

def discover_fragments(base_dir:str,symbol:str,tf_minutes:int,session:str):
    root=Path(base_dir)/"history"
    if not root.is_dir(): return []
    prefix=f"{symbol.upper()}_{int(tf_minutes)}m_{str(session).lower()}"
    out=[]
    for p in root.glob("*.csv"):
        stem=p.stem.lower()
        if stem.startswith(prefix.lower()):
            out.append(str(p.resolve()))
    return sorted(out)

def stitch_fragments(paths,tf_seconds:int,session:str):
    merged={}; reports=[]; overlaps=0; conflicts=0
    for path in paths:
        bars,report=load_csv(path,tf_seconds,session)
        reports.append(report)
        for b in bars:
            if b.ts in merged:
                overlaps+=1
                if not _same(merged[b.ts],b): conflicts+=1
            merged[b.ts]=b                       # later deterministic path wins
    bars=[merged[k] for k in sorted(merged)]
    return bars,{"schema_version":"icarus-history-stitch-v1","session":session,
                 "sources":[r.to_dict() for r in reports],"source_count":len(reports),
                 "bars":len(bars),"overlaps":overlaps,"conflicts":conflicts,
                 "first_ts":bars[0].ts if bars else None,"last_ts":bars[-1].ts if bars else None,
                 "resolution":"LEXICOGRAPHIC_LATER_SOURCE_WINS","execution_authorized":False}

def _write_csv(path:Path,bars):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".history-",dir=str(path.parent),text=True)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="") as f:
            w=csv.writer(f); w.writerow(["ts","open","high","low","close","volume"])
            for b in bars: w.writerow([b.ts,b.o,b.h,b.l,b.c,b.v])
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def prepare_session_history(base_dir:str,symbol:str,tf_minutes:int,session:str):
    """Return (generated_csv_path, stitch_report) or (None,None).

    Only explicitly session-labelled canonical fragments are auto-stitched:
    history/<SYMBOL>_<TF>m_rth*.csv or ..._eth*.csv. A generic exact
    history/<SYMBOL>_<TF>m.csv remains higher-priority in the runtime.
    """
    session=str(session).lower()
    if session not in ("rth","eth"): return None,None
    paths=discover_fragments(base_dir,symbol,tf_minutes,session)
    if not paths: return None,None
    bars,report=stitch_fragments(paths,int(tf_minutes)*60,session)
    if not bars: return None,report
    out=Path(base_dir)/"state"/"history"/"stitched"/f"{symbol.upper()}_{int(tf_minutes)}m_{session}.csv"
    _write_csv(out,bars)
    manifest=out.with_suffix(".json")
    manifest.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    return str(out),report
