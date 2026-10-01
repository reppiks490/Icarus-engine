"""Deterministic historical-data validation, stitching and provenance for ICARUS."""
from __future__ import annotations
import csv, hashlib, json, os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable, List, Optional
from .pine.timeframe import Bar

@dataclass
class HistoryReport:
    source: str
    rows_read: int = 0
    bars_valid: int = 0
    duplicates: int = 0
    rejected: int = 0
    gaps: int = 0
    first_ts: Optional[int] = None
    last_ts: Optional[int] = None
    sha256: str = ""
    session: str = "UNKNOWN"
    def to_dict(self): return asdict(self)

def _ts(v: str) -> int:
    v=v.strip()
    if v.replace(".","",1).isdigit(): return int(float(v))
    return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())

def load_csv(path: str, tf_seconds: int, session: str="UNKNOWN"):
    raw=open(path,"rb").read()
    report=HistoryReport(source=os.path.normpath(path),sha256=hashlib.sha256(raw).hexdigest(),session=session)
    rows={}
    text=raw.decode("utf-8-sig").splitlines()
    for row in csv.DictReader(text):
        report.rows_read += 1
        try:
            t=_ts(row.get("ts") or row.get("time") or row.get("timestamp") or "")
            o,h,l,c=(float(row[k]) for k in ("open","high","low","close"))
            v=float(row.get("volume") or 0)
            if min(o,h,l,c)<=0 or h<max(o,c,l) or l>min(o,c,h): raise ValueError("invalid OHLC")
            b=Bar(t,o,h,l,c,v)
            if t in rows: report.duplicates += 1
            rows[t]=b
        except Exception: report.rejected += 1
    bars=[rows[k] for k in sorted(rows)]
    report.bars_valid=len(bars)
    if bars:
        report.first_ts,bars_last=bars[0].ts,bars[-1].ts
        report.last_ts=bars_last
        report.gaps=sum(1 for a,b in zip(bars,bars[1:]) if b.ts-a.ts > tf_seconds*1.5)
    return bars,report

def stitch(paths: Iterable[str], tf_seconds: int, session: str="UNKNOWN"):
    merged={}; reports=[]
    for p in paths:
        bars,r=load_csv(p,tf_seconds,session); reports.append(r)
        for b in bars: merged[b.ts]=b
    return [merged[k] for k in sorted(merged)], reports

def write_manifest(path: str, reports: List[HistoryReport], loaded: int):
    payload={"schema_version":"icarus-history-manifest-v1","loaded":loaded,"sources":[r.to_dict() for r in reports]}
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: json.dump(payload,f,indent=2,sort_keys=True)
    return payload
