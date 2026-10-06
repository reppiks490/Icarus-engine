"""Official U.S. economic-event clock for ICARUS.

Sources are first-party calendars only.  Raw/current schedules and historical schedule
versions stay in an Actions cache; the repository receives a compact manifest and an
upcoming-event feed for research/UI use.

The history ledger is deliberate: scheduled release times can change.  A backtest that
uses "time until CPI" or similar features must be able to reconstruct the schedule that
was known at the decision time rather than silently using a later revision.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from datetime import datetime, date, time, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .http import FeedError, get_bytes

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

SOURCES = {
    "BLS": "https://www.bls.gov/schedule/news_release/bls.ics",
    "BEA": "https://www.bea.gov/news/schedule/full",
    "CENSUS": "https://www.census.gov/economic-indicators/calendar-listview.html",
    "FOMC": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
}

MONTHS = {
    name: i for i, name in enumerate(
        ("January","February","March","April","May","June",
         "July","August","September","October","November","December"), 1
    )
}
MONTH_RE = "|".join(MONTHS)

HIGH_PATTERNS = (
    "consumer price index", "producer price index", "employment situation",
    "employment cost index", "gross domestic product", "gdp ", "personal income and outlays",
    "retail and food services", "durable goods", "international trade in goods and services",
    "new residential construction", "fomc", "federal open market committee",
)
MEDIUM_PATTERNS = (
    "job openings", "jolts", "productivity and costs", "import and export price",
    "construction spending", "new residential sales", "wholesale trade",
    "manufacturing and trade", "business formation",
)

def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(s or "")).strip())

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def _category(title: str) -> str:
    x = title.lower()
    if "fomc" in x or "federal open market" in x:
        return "policy"
    if any(k in x for k in ("consumer price","producer price","pce","price index","inflation")):
        return "inflation"
    if any(k in x for k in ("employment","job openings","jolts","earnings","labor","unemployment")):
        return "labor"
    if any(k in x for k in ("gdp","gross domestic","retail","durable","construction","housing",
                             "residential","manufacturing","trade","income and outlays")):
        return "growth"
    return "macro"

def _impact(title: str) -> str:
    x = title.lower()
    if any(p in x for p in HIGH_PATTERNS):
        return "high"
    if any(p in x for p in MEDIUM_PATTERNS):
        return "medium"
    return "low"

def _key(source: str, title: str, reference_period: str | None = None, stable_id: str | None = None) -> str:
    if stable_id:
        raw=f"{source}|id|{stable_id}"
    else:
        raw=f"{source}|{_slug(title)}|{_slug(reference_period or '')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]

def _record(source: str, title: str, *, scheduled: datetime | None = None,
            event_date: date | None = None, reference_period: str | None = None,
            stable_id: str | None = None, source_url: str | None = None,
            timing_basis: str = "source_schedule") -> dict:
    title=_norm(title)
    if scheduled is not None:
        if scheduled.tzinfo is None:
            scheduled=scheduled.replace(tzinfo=ET)
        et=scheduled.astimezone(ET)
        utc=scheduled.astimezone(UTC)
        d=et.date()
        et_s=et.isoformat()
        utc_s=utc.isoformat()
        known=True
    else:
        if event_date is None:
            raise ValueError("event_date required for date-only event")
        d=event_date
        et_s=utc_s=None
        known=False
    return {
        "source":source,
        "event_key":_key(source,title,reference_period,stable_id),
        "stable_id":stable_id,
        "title":title,
        "category":_category(title),
        "impact":_impact(title),
        "reference_period":_norm(reference_period) or None,
        "event_date":d.isoformat(),
        "scheduled_at_et":et_s,
        "scheduled_at_utc":utc_s,
        "time_known":known,
        "timing_basis":timing_basis,
        "source_url":source_url or SOURCES.get(source),
    }

def _unfold_ics(text: str) -> list[str]:
    out=[]
    for raw in text.replace("\r\n","\n").replace("\r","\n").split("\n"):
        if raw.startswith((" ","\t")) and out:
            out[-1]+=raw[1:]
        else:
            out.append(raw)
    return out

def _ics_unescape(s: str) -> str:
    return (s.replace("\\n"," ").replace("\\N"," ")
             .replace("\\, ",", ").replace("\\,",",")
             .replace("\\;",";").replace("\\\\","\\"))

def _parse_ics_dt(prop: str, value: str) -> tuple[datetime | None,date | None]:
    value=value.strip()
    if "VALUE=DATE" in prop or re.fullmatch(r"\d{8}",value):
        return None, datetime.strptime(value[:8],"%Y%m%d").date()
    z=value.endswith("Z")
    raw=value[:-1] if z else value
    fmt="%Y%m%dT%H%M%S" if len(raw)>=15 else "%Y%m%dT%H%M"
    dt=datetime.strptime(raw,fmt)
    if z:
        return dt.replace(tzinfo=UTC), None
    m=re.search(r"TZID=([^;:]+)",prop)
    zone=ET
    if m:
        name=m.group(1).strip('"')
        aliases={"US-Eastern":"America/New_York","Eastern Standard Time":"America/New_York"}
        try:
            zone=ZoneInfo(aliases.get(name,name))
        except Exception:
            zone=ET
    return dt.replace(tzinfo=zone), None

def parse_bls_ics(raw: bytes) -> pd.DataFrame:
    text=raw.decode("utf-8-sig",errors="replace")
    rows=[]
    cur=None
    for line in _unfold_ics(text):
        if line=="BEGIN:VEVENT":
            cur={}
            continue
        if line=="END:VEVENT":
            if cur:
                dt=cur.get("_dt")
                d=cur.get("_date")
                title=_ics_unescape(cur.get("SUMMARY") or "")
                if title and (dt is not None or d is not None):
                    rows.append(_record(
                        "BLS",title,scheduled=dt,event_date=d,
                        reference_period=cur.get("DESCRIPTION"),
                        stable_id=cur.get("UID"),source_url=SOURCES["BLS"],
                    ))
            cur=None
            continue
        if cur is None or ":" not in line:
            continue
        prop,val=line.split(":",1)
        name=prop.split(";",1)[0].upper()
        if name=="DTSTART":
            try:
                cur["_dt"],cur["_date"]=_parse_ics_dt(prop,val)
            except Exception:
                continue
        elif name in ("SUMMARY","DESCRIPTION","UID"):
            cur[name]=val
    return pd.DataFrame(rows)

class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[]; self._row=None; self._cell=None; self._all=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="tr": self._row=[]
        elif tag.lower() in ("td","th") and self._row is not None: self._cell=[]
    def handle_data(self,data):
        self._all.append(data)
        if self._cell is not None: self._cell.append(data)
    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag in ("td","th") and self._row is not None and self._cell is not None:
            self._row.append(_norm(" ".join(self._cell))); self._cell=None
        elif tag=="tr" and self._row is not None:
            if any(self._row): self.rows.append(self._row)
            self._row=None
    @property
    def text(self): return _norm(" ".join(self._all))

def _table_rows(raw: bytes) -> tuple[list[list[str]],str]:
    p=_TableParser()
    p.feed(raw.decode("utf-8",errors="replace"))
    return p.rows,p.text

def _extract_year(page_text: str, default: int) -> int:
    years=[int(x) for x in re.findall(r"\b20\d{2}\b",page_text)]
    return default if not years else max([y for y in years if abs(y-default)<=2] or [default])

def _extract_dt(cells: list[str], default_year: int) -> tuple[datetime | None,date | None]:
    joined=" | ".join(cells)
    tm=re.search(r"\b(1[0-2]|0?[1-9]):([0-5]\d)\s*([AP]M)\b",joined,re.I)
    explicit=re.search(rf"\b({MONTH_RE})\s+(\d{{1,2}})(?:,)?\s+(20\d{{2}})\b",joined,re.I)
    if explicit:
        mon=MONTHS[explicit.group(1).title()]; day=int(explicit.group(2)); year=int(explicit.group(3))
    else:
        short=re.search(rf"\b({MONTH_RE})\s+(\d{{1,2}})\b",joined,re.I)
        if not short: return None,None
        mon=MONTHS[short.group(1).title()]; day=int(short.group(2)); year=default_year
    d=date(year,mon,day)
    if not tm: return None,d
    h=int(tm.group(1))%12 + (12 if tm.group(3).upper()=="PM" else 0)
    return datetime.combine(d,time(h,int(tm.group(2))),ET),None

def _reference_period(cells: list[str], scheduled_date: date) -> str | None:
    candidates=[]
    for c in cells:
        for m in re.finditer(rf"\b({MONTH_RE})\s+(20\d{{2}})\b",c,re.I):
            s=m.group(0)
            if _slug(s)!=_slug(f"{scheduled_date.strftime('%B')} {scheduled_date.year}"):
                candidates.append(s)
        q=re.search(r"\b([1-4](?:st|nd|rd|th)? Quarter(?: and Year)?\s+20\d{2})\b",c,re.I)
        if q: candidates.append(q.group(1))
    return candidates[0] if candidates else None

def _title_from_cells(cells: list[str]) -> str:
    ignore={"view","news","data","visual data","article","release","date","time","reference period"}
    choices=[]
    for c in cells:
        s=_norm(c)
        if not s or s.lower() in ignore: continue
        if re.fullmatch(r"(?:N|D|V|A)",s): continue
        if re.fullmatch(r"\d{1,2}:\d{2}\s*[AP]M",s,re.I): continue
        if re.fullmatch(rf"({MONTH_RE})\s+\d{{1,2}}(?:,?\s+20\d{{2}})?(?:\s+\d{{1,2}}:\d{{2}}\s*[AP]M)?",s,re.I): continue
        choices.append(s)
    if not choices: return ""
    return max(choices,key=len)

def parse_release_table(raw: bytes, source: str, observed_at: pd.Timestamp | None = None) -> pd.DataFrame:
    observed_at=pd.Timestamp.now(tz="UTC") if observed_at is None else pd.Timestamp(observed_at)
    rows,text=_table_rows(raw)
    year=_extract_year(text,observed_at.year)
    out=[]
    for cells in rows:
        dt,d=_extract_dt(cells,year)
        if dt is None and d is None: continue
        title=_title_from_cells(cells)
        if not title: continue
        ed=dt.astimezone(ET).date() if dt is not None else d
        ref=_reference_period(cells,ed)
        out.append(_record(source,title,scheduled=dt,event_date=d,reference_period=ref,source_url=SOURCES[source]))
    return pd.DataFrame(out).drop_duplicates("event_key",keep="last") if out else pd.DataFrame()

def parse_fomc_html(raw: bytes, year: int | None = None) -> pd.DataFrame:
    _,text=_table_rows(raw)
    year=year or pd.Timestamp.now(tz="UTC").year
    # The Fed page is not chronological by heading: the current year is followed by
    # prior years, while a future-year section may appear elsewhere. Bound the target
    # section by the *next FOMC heading in document order*, not by year+1.
    headings=list(re.finditer(r"\b(20\d{2})\s+FOMC Meetings\b",text,re.I))
    target=None
    for i,h in enumerate(headings):
        if int(h.group(1))==int(year):
            target=(i,h)
            break
    if target is None:
        return pd.DataFrame()
    i,h=target
    end=headings[i+1].start() if i+1<len(headings) else len(text)
    tail=text[h.end():end]
    matches=list(re.finditer(rf"\b({MONTH_RE})\s+(\d{{1,2}})(?:\s*[-–]\s*(\d{{1,2}}))?(\*)?",tail,re.I))
    out=[]
    meeting_index=0
    for m in matches:
        # The page also contains single-date minute-release references inside each
        # meeting block. Regular scheduled meetings are represented as date ranges;
        # reject single dates rather than misclassifying minutes as policy decisions.
        if not m.group(3):
            continue
        meeting_index+=1
        mon=MONTHS[m.group(1).title()]
        decision_day=int(m.group(3))
        try: d=date(year,mon,decision_day)
        except ValueError: continue
        sep=bool(m.group(4))
        title="FOMC policy decision" + (" (SEP meeting)" if sep else "")
        out.append(_record(
            "FOMC",title,event_date=d,stable_id=f"{year}-meeting-{meeting_index}",
            source_url=SOURCES["FOMC"],timing_basis="meeting_end_date; statement time not asserted",
        ))
    return pd.DataFrame(out)

def _sha(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

def _schedule_version(row: pd.Series) -> str:
    raw="|".join(str(row.get(k) or "") for k in
                 ("source","event_key","event_date","scheduled_at_et","title","reference_period"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]

def collect(cache_dir: str | Path, observed_at: pd.Timestamp | None = None) -> tuple[pd.DataFrame,pd.DataFrame,dict]:
    observed_at=pd.Timestamp.now(tz="UTC") if observed_at is None else pd.Timestamp(observed_at)
    root=Path(cache_dir)/"economic_events"
    root.mkdir(parents=True,exist_ok=True)
    current=[]; status={}
    fetchers={
        "BEA": lambda raw: parse_release_table(raw,"BEA",observed_at),
        "CENSUS": lambda raw: parse_release_table(raw,"CENSUS",observed_at),
        "FOMC": lambda raw: parse_fomc_html(raw,observed_at.year),
    }
    for source,url in SOURCES.items():
        try:
            note=None
            if source=="BLS":
                try:
                    df=parse_bls_ics(get_bytes(url))
                    if df.empty:
                        raise FeedError("BLS ICS returned zero usable events")
                    note="ics"
                except Exception as ics_error:
                    # GitHub-hosted runners can receive 403 on BLS's text/calendar
                    # endpoint while the first-party HTML schedule remains available.
                    # Stay on BLS as source-of-record rather than substituting a
                    # third-party economic calendar.
                    html_url=f"https://www.bls.gov/schedule/{observed_at.year}/"
                    df=parse_release_table(get_bytes(html_url),"BLS",observed_at)
                    if df.empty:
                        raise FeedError(
                            f"BLS ICS failed ({type(ics_error).__name__}: {ics_error}); "
                            "BLS HTML fallback returned zero usable events"
                        )
                    note="html_fallback"
            else:
                df=fetchers[source](get_bytes(url))
            if df.empty: raise FeedError(f"{source} calendar returned zero usable events")
            current.append(df)
            status[source]={"status":"ok","rows":int(len(df))}
            if note:
                status[source]["transport"]=note
        except Exception as e:
            status[source]={"status":"error","rows":0,"error":f"{type(e).__name__}: {e}"}
    if not current:
        raise FeedError("all official economic-event sources failed")
    cur=pd.concat(current,ignore_index=True)
    cur["observed_at"]=observed_at.isoformat()
    cur["schedule_version"]=cur.apply(_schedule_version,axis=1)
    cur=cur.sort_values(["event_date","source","title"]).reset_index(drop=True)
    cur.to_csv(root/"current.csv.gz",index=False,compression="gzip")

    hp=root/"schedule_history.csv.gz"
    old=pd.read_csv(hp,compression="gzip") if hp.exists() else pd.DataFrame()
    add=cur.copy()
    add["first_seen_at"]=observed_at.isoformat()
    hist=pd.concat([old,add],ignore_index=True) if not old.empty else add
    hist=hist.drop_duplicates(["schedule_version"],keep="first")
    hist.to_csv(hp,index=False,compression="gzip")
    return cur,hist,status

def build_outputs(cur: pd.DataFrame,hist: pd.DataFrame,status: dict,observed_at: pd.Timestamp,
                  manifest_path: Path, upcoming_path: Path) -> dict:
    today=observed_at.tz_convert("America/New_York").date()
    horizon=today+pd.Timedelta(days=120)
    dates=pd.to_datetime(cur["event_date"],errors="coerce").dt.date
    upcoming=cur[(dates>=today)&(dates<=horizon)].copy()
    upcoming=upcoming.sort_values(["event_date","scheduled_at_et","source","title"])
    cols=["source","event_key","title","category","impact","reference_period","event_date",
          "scheduled_at_et","scheduled_at_utc","time_known","timing_basis"]
    payload={
        "schema":"icarus.economic_events.upcoming/1",
        "generated_at":observed_at.isoformat(),
        "timezone":"America/New_York",
        "events":upcoming[cols].where(pd.notna(upcoming[cols]),None).to_dict("records"),
    }
    upcoming_path.parent.mkdir(parents=True,exist_ok=True)
    upcoming_path.write_text(json.dumps(payload,indent=2,sort_keys=True,default=str))
    manifest={
        "schema":"icarus.economic_events/1",
        "generated_at":observed_at.isoformat(),
        "sources":status,
        "current_events":int(len(cur)),
        "schedule_versions":int(len(hist)),
        "high_impact_current":int((cur["impact"]=="high").sum()),
        "time_known_current":int(cur["time_known"].astype(bool).sum()),
        "current_sha256":_sha(cur),
        "history_sha256":_sha(hist),
        "upcoming_rows":int(len(upcoming)),
        "causality":"schedule_history records the first observed version of each scheduled event; use only versions first_seen_at <= decision time",
    }
    manifest_path.parent.mkdir(parents=True,exist_ok=True)
    manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True))
    return manifest

def main():
    cache=os.environ.get("ICARUS_EVENTS_CACHE",".economic_events_cache")
    manifest=Path(os.environ.get("ICARUS_EVENTS_MANIFEST","automation_intelligence/cl_lab/economic_events_manifest.json"))
    upcoming=Path(os.environ.get("ICARUS_EVENTS_UPCOMING","automation_intelligence/cl_lab/economic_events_upcoming.json"))
    now=pd.Timestamp.now(tz="UTC")
    cur,hist,status=collect(cache,now)
    m=build_outputs(cur,hist,status,now,manifest,upcoming)
    good=[k for k,v in status.items() if v["status"]=="ok"]
    print(json.dumps({"sources_ok":good,"current_events":m["current_events"],"schedule_versions":m["schedule_versions"],"upcoming":m["upcoming_rows"]}))
    if len(good)<2:
        raise SystemExit(f"economic-event integrity failure: only {len(good)} official sources usable")

if __name__=="__main__":
    main()
