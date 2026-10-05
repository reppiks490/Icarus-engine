"""FRED/ALFRED point-in-time macro fabric for ICARUS research.

Raw observations/vintages remain in Actions cache. Repository outputs are manifests only.
ALFRED uses FRED's realtime/vintage API semantics so backtests can select only information
known as-of a historical date and avoid revised-data leakage.
"""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pandas as pd

API="https://api.stlouisfed.org/fred"

SERIES={
 "rates":["DFF","SOFR","DGS2","DGS5","DGS10","DGS30","DFII5","DFII10","T10Y2Y","T10Y3M","T5YIE","T10YIE"],
 "liquidity":["WALCL","WRESBAL","RRPONTSYD","WTREGEN","M2SL"],
 "credit":["BAMLH0A0HYM2","BAMLC0A0CM","NFCI","STLFSI4"],
 "inflation":["CPIAUCSL","CPILFESL","PCEPI","PCEPILFE","PPIACO"],
 "labor":["PAYEMS","UNRATE","ICSA","CCSA","JTSJOL"],
 "growth":["GDPC1","INDPRO","RSAFS","HOUST","UMCSENT"],
 "risk":["VIXCLS","NASDAQ100","SP500"],
}
VINTAGE_SERIES={"CPIAUCSL","CPILFESL","PCEPI","PCEPILFE","PAYEMS","UNRATE","GDPC1","RSAFS","INDPRO","HOUST"}

def _get(endpoint,key,**params):
    params.update(api_key=key,file_type="json")
    req=Request(f"{API}/{endpoint}?{urlencode(params)}",headers={"User-Agent":"ICARUS-research/1.0"})
    with urlopen(req,timeout=45) as r:
        return json.loads(r.read())

def observations(series,key,**params):
    rows=_get("series/observations",key,series_id=series,**params).get("observations",[])
    out=[]
    for x in rows:
        v=x.get("value")
        out.append({"series_id":series,"observation_date":x.get("date"),
                    "realtime_start":x.get("realtime_start"),"realtime_end":x.get("realtime_end"),
                    "value":None if v in (None,".") else float(v)})
    return pd.DataFrame(out)

def vintage_dates(series,key):
    return _get("series/vintagedates",key,series_id=series,limit=10000).get("vintage_dates",[])

def point_in_time(series,key,as_of):
    """Values known on as_of. Never substitute today's revised history."""
    return observations(series,key,realtime_start=as_of,realtime_end=as_of)

def _write(df,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    df.to_csv(path,index=False,compression="gzip")

def validate_manifest(manifest):
    """Fail closed when a configured macro source did not actually deliver usable data."""
    bad=[]
    for sid, ent in manifest["series"].items():
        if ent.get("status") != "ok" or int(ent.get("rows") or 0) <= 0:
            bad.append(sid)
            continue
        if sid in VINTAGE_SERIES and int(ent.get("vintage_dates") or 0) <= 0:
            bad.append(sid)
    return sorted(set(bad))

def refresh(cache_dir,key,now=None):
    now=pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    root=Path(cache_dir)/"fred_alfred"
    manifest={"schema":"icarus.fred_alfred/2","generated_at":now.isoformat(),"series":{}}
    for family,ids in SERIES.items():
        for sid in ids:
            ent={"family":family,"point_in_time":sid in VINTAGE_SERIES}
            try:
                cur=observations(sid,key)
                if cur.empty:
                    raise RuntimeError("FRED returned zero observations")
                if "observation_date" not in cur or cur["observation_date"].isna().all():
                    raise RuntimeError("FRED observations contain no usable dates")
                _write(cur,root/"current"/f"{sid}.csv.gz")
                ent.update(status="ok",rows=len(cur),
                           observation_start=cur.observation_date.min(),
                           observation_end=cur.observation_date.max())
                if sid in VINTAGE_SERIES:
                    vd=vintage_dates(sid,key)
                    if not vd:
                        raise RuntimeError("ALFRED returned zero vintage dates")
                    (root/"vintage_dates").mkdir(parents=True,exist_ok=True)
                    (root/"vintage_dates"/f"{sid}.json").write_text(json.dumps(vd))
                    ent["vintage_dates"]=len(vd)
                    pit=point_in_time(sid,key,now.date().isoformat())
                    if pit.empty:
                        raise RuntimeError("ALFRED point-in-time snapshot is empty")
                    _write(pit,root/"pit"/f"{sid}__{now.date().isoformat()}.csv.gz")
                    ent["pit_rows"]=len(pit)
                raw=(root/"current"/f"{sid}.csv.gz").read_bytes()
                ent["sha256"]=hashlib.sha256(raw).hexdigest()
            except Exception as e:
                ent.update(status="error",error=f"{type(e).__name__}: {e}")
            manifest["series"][sid]=ent
    return manifest

def main():
    key=(os.environ.get("FRED_API_KEY") or "").strip()
    if not key:
        raise SystemExit("FRED_API_KEY is not configured")
    cache=os.environ.get("ICARUS_FRED_CACHE",".cl_cache")
    out=os.environ.get("ICARUS_FRED_MANIFEST","automation_intelligence/cl_lab/fred_alfred_manifest.json")
    man=refresh(cache,key)
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    Path(out).write_text(json.dumps(man,indent=2,sort_keys=True))
    bad=validate_manifest(man)
    summary={"series":len(man["series"]),"ok":len(man["series"])-len(bad),"errors":bad,"manifest":out}
    print(json.dumps(summary))
    if bad:
        raise SystemExit(f"FRED/ALFRED integrity failure: {len(bad)} series invalid: {','.join(bad)}")

if __name__=="__main__":
    main()
