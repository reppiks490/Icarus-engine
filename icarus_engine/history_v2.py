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


def assess_quality(report, target_bars: int):
    """Conservative research-readiness gate; does not authorize or block order execution.

    Gaps are reported but intentionally not failed here because exchange/session
    closures can create legitimate timestamp gaps. Rejected/duplicate ratios and
    usable depth are provider-agnostic and safe to gate on.
    """
    d=report.to_dict() if hasattr(report,"to_dict") else dict(report or {})
    read=max(1,int(d.get("rows_read") or 0)); valid=int(d.get("bars_valid") or 0)
    rejected=int(d.get("rejected") or 0); duplicates=int(d.get("duplicates") or 0)
    reasons=[]
    if valid<=0: reasons.append("NO_VALID_BARS")
    if valid<int(target_bars): reasons.append("BELOW_TARGET_DEPTH")
    if rejected/read>0.01: reasons.append("REJECT_RATE_GT_1PCT")
    if duplicates/read>0.01: reasons.append("DUPLICATE_RATE_GT_1PCT")
    if rejected/read>0.05: status="INVALID"
    elif not reasons: status="READY"
    else: status="DEGRADED"
    return {"status":status,"reasons":reasons,"target_bars":int(target_bars),
            "bars_valid":valid,"reject_rate":rejected/read,"duplicate_rate":duplicates/read,
            "time_gaps_observed":int(d.get("gaps") or 0),
            "execution_authorized":False}
