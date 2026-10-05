"""SEC EDGAR event + XBRL fabric for ICARUS.

Uses only public SEC machine-readable APIs. Filing acceptance timestamps are preserved
as the causal event time; report period/end dates are never substituted for availability.
"""
from __future__ import annotations

import hashlib, json, os, time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd

from .http import FeedError, get_bytes

SEC_WWW="https://www.sec.gov/"
SEC_DATA="https://data.sec.gov/"
DEFAULT_TICKERS=("NVDA","AAPL","MSFT","AVGO","AMZN","META","GOOGL","TSLA")
DEFAULT_CIKS={
    "NVDA":"0001045810","AAPL":"0000320193","MSFT":"0000789019","AVGO":"0001730168",
    "AMZN":"0001018724","META":"0001326801","GOOGL":"0001652044","TSLA":"0001318605",
}
FORMS={"10-K","10-K/A","10-Q","10-Q/A","8-K","8-K/A"}
CONCEPTS={
    "Revenues","SalesRevenueNet","NetIncomeLoss","OperatingIncomeLoss","Assets","Liabilities",
    "StockholdersEquity","CashAndCashEquivalentsAtCarryingValue","EarningsPerShareDiluted",
    "CommonStockSharesOutstanding","NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment","ResearchAndDevelopmentExpense",
}
_last_request=0.0

def _ua():
    return (os.environ.get("SEC_USER_AGENT") or
            "ICARUS research bot github.com/reppiks490/Icarus-engine").strip()

def _get(url):
    global _last_request
    wait=0.13-(time.monotonic()-_last_request)
    if wait>0:
        time.sleep(wait)
    # Do not request compressed transfer encoding here: the shared stdlib HTTP helper
    # returns response bytes verbatim and intentionally does not transparently gunzip.
    raw=get_bytes(url,headers={"User-Agent":_ua(),"Accept":"application/json"})
    _last_request=time.monotonic()
    return json.loads(raw)

def ticker_map():
    """Return a ticker->CIK map with a cloud-safe seed for the default ICARUS universe.

    SEC's www.sec.gov ticker map can reject hosted-runner traffic even when the
    data.sec.gov APIs remain usable.  The default CIKs are stable identifiers and
    are seeded locally; the remote map is used to extend coverage for custom tickers.
    """
    out=dict(DEFAULT_CIKS)
    try:
        raw=_get(urljoin(SEC_WWW,"files/company_tickers.json"))
    except Exception:
        return out
    for row in raw.values():
        ticker=str(row.get("ticker") or "").upper()
        cik=row.get("cik_str")
        if ticker and cik is not None:
            out[ticker]=f"{int(cik):010d}"
    return out

def _accepted(value):
    if not value:
        return pd.NaT
    s=str(value)
    # Do not invent a timezone for a naive timestamp. Preserve raw value separately.
    if not (s.endswith("Z") or ("+" in s[10:] or "-" in s[10:])):
        return pd.NaT
    return pd.to_datetime(s,errors="coerce",utc=True)

def _recent_rows(payload,ticker,cik):
    recent=((payload.get("filings") or {}).get("recent") or {})
    n=max((len(v) for v in recent.values() if isinstance(v,list)),default=0)
    rows=[]
    for i in range(n):
        rec={k:(v[i] if isinstance(v,list) and i<len(v) else None) for k,v in recent.items()}
        form=str(rec.get("form") or "")
        if form not in FORMS:
            continue
        raw_accept=rec.get("acceptanceDateTime")
        rows.append({
            "ticker":ticker,"cik":cik,"form":form,"accession":rec.get("accessionNumber"),
            "filing_date":rec.get("filingDate"),"report_date":rec.get("reportDate"),
            "acceptance_datetime_raw":raw_accept,"accepted_at":_accepted(raw_accept),
            "primary_document":rec.get("primaryDocument"),
            "primary_doc_description":rec.get("primaryDocDescription"),
            "items":rec.get("items"),"file_number":rec.get("fileNumber"),
        })
    return rows

def filings_for_ticker(ticker,cik,max_history_files=8):
    base=_get(urljoin(SEC_DATA,f"submissions/CIK{cik}.json"))
    rows=_recent_rows(base,ticker,cik)
    for entry in ((base.get("filings") or {}).get("files") or [])[:max_history_files]:
        name=entry.get("name")
        if not name:
            continue
        hist=_get(urljoin(SEC_DATA,f"submissions/{name}"))
        # historical files are columnar directly rather than nested under filings.recent
        rows.extend(_recent_rows({"filings":{"recent":hist}},ticker,cik))
    df=pd.DataFrame(rows)
    if df.empty:
        return df
    df=df.drop_duplicates(["ticker","accession"],keep="last")
    df["filing_date"]=pd.to_datetime(df["filing_date"],errors="coerce")
    df["report_date"]=pd.to_datetime(df["report_date"],errors="coerce")
    return df.sort_values(["ticker","filing_date","accession"])

def companyfacts_for_ticker(ticker,cik,acceptance_by_accn):
    payload=_get(urljoin(SEC_DATA,f"api/xbrl/companyfacts/CIK{cik}.json"))
    rows=[]
    facts=(payload.get("facts") or {}).get("us-gaap") or {}
    for concept in CONCEPTS:
        node=facts.get(concept) or {}
        for unit,vals in (node.get("units") or {}).items():
            for v in vals:
                form=str(v.get("form") or "")
                if form not in {"10-K","10-K/A","10-Q","10-Q/A"}:
                    continue
                accn=v.get("accn")
                rows.append({
                    "ticker":ticker,"cik":cik,"concept":concept,"unit":unit,"value":v.get("val"),
                    "start":v.get("start"),"end":v.get("end"),"filed":v.get("filed"),
                    "form":form,"fy":v.get("fy"),"fp":v.get("fp"),"accession":accn,
                    "accepted_at":acceptance_by_accn.get(accn,pd.NaT),
                })
    df=pd.DataFrame(rows)
    if df.empty:
        return df
    for c in ("start","end","filed"):
        df[c]=pd.to_datetime(df[c],errors="coerce")
    return df.drop_duplicates(["ticker","concept","unit","accession","start","end"],keep="last")

def _write(df,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    df.to_csv(path,index=False,compression="gzip")

def refresh(cache_dir,tickers=None):
    tickers=tuple(tickers or DEFAULT_TICKERS)
    mapping=ticker_map()
    root=Path(cache_dir)/"sec_edgar"
    filings_path=root/"filings.csv.gz"
    prior=pd.DataFrame()
    if filings_path.exists():
        try:
            prior=pd.read_csv(filings_path,compression="gzip")
            if "accepted_at" in prior:
                prior["accepted_at"]=pd.to_datetime(prior["accepted_at"],errors="coerce",utc=True)
            for col in ("filing_date","report_date"):
                if col in prior:
                    prior[col]=pd.to_datetime(prior[col],errors="coerce")
        except Exception:
            prior=pd.DataFrame()
    all_filings=[]; all_facts=[]; status={}
    for ticker in tickers:
        cik=mapping.get(ticker)
        if not cik:
            status[ticker]={"status":"error","error":"ticker not found in SEC mapping"}
            continue
        try:
            old=prior[prior["ticker"].eq(ticker)].copy() if not prior.empty and "ticker" in prior else pd.DataFrame()
            # Historical submission shards are a seed operation. Hourly refreshes only need
            # the SEC recent-submissions payload; cached historical accessions are retained.
            recent=filings_for_ticker(ticker,cik,max_history_files=0 if not old.empty else 8)
            filings=(pd.concat([old,recent],ignore_index=True)
                     .drop_duplicates(["ticker","accession"],keep="last")
                     if not old.empty else recent)
            amap={r.accession:r.accepted_at for r in filings.itertuples() if pd.notna(r.accepted_at)}
            facts=companyfacts_for_ticker(ticker,cik,amap)
            if filings.empty:
                raise FeedError("zero target filings")
            all_filings.append(filings)
            all_facts.append(facts)
            status[ticker]={"status":"ok","cik":cik,"filings":len(filings),"facts":len(facts),
                            "accepted_timestamps":int(filings["accepted_at"].notna().sum()),
                            "history_seeded":bool(not old.empty)}
        except Exception as e:
            status[ticker]={"status":"error","cik":cik,"error":f"{type(e).__name__}: {e}"}
    filings=pd.concat(all_filings,ignore_index=True) if all_filings else pd.DataFrame()
    facts=pd.concat(all_facts,ignore_index=True) if all_facts else pd.DataFrame()
    if filings.empty:
        raise FeedError("SEC EDGAR returned zero usable filings")
    _write(filings,root/"filings.csv.gz")
    _write(facts,root/"companyfacts.csv.gz")
    return filings,facts,status

def main():
    cache=os.environ.get("ICARUS_SEC_CACHE",".sec_edgar_cache")
    out=Path(os.environ.get("ICARUS_SEC_MANIFEST","automation_intelligence/cl_lab/sec_edgar_manifest.json"))
    tickers=tuple(x.strip().upper() for x in os.environ.get("ICARUS_SEC_TICKERS",",".join(DEFAULT_TICKERS)).split(",") if x.strip())
    filings,facts,status=refresh(cache,tickers)
    manifest={
        "schema":"icarus.sec_edgar/1","generated_at":pd.Timestamp.now(tz="UTC").isoformat(),
        "tickers":status,"filing_rows":len(filings),"fact_rows":len(facts),
        "filing_sha256":hashlib.sha256(filings.to_csv(index=False).encode()).hexdigest(),
        "facts_sha256":hashlib.sha256(facts.to_csv(index=False).encode()).hexdigest(),
        "causality":"acceptanceDateTime is the availability timestamp; report/end dates are descriptive only",
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(manifest,indent=2,sort_keys=True))
    bad=[k for k,v in status.items() if v.get("status")!="ok"]
    print(json.dumps({"tickers":len(status),"filing_rows":len(filings),"fact_rows":len(facts),"errors":bad}))
    if len(bad)==len(status):
        raise SystemExit("SEC EDGAR integrity failure: all configured tickers failed")

if __name__=="__main__":
    main()
