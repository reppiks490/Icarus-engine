import json
import pandas as pd

from cl_lab.feeds import economic_events as ev


BLS_ICS=b"""BEGIN:VCALENDAR
BEGIN:VEVENT
UID:cpi-2026-09@bls.gov
DTSTART;TZID=America/New_York:20261014T083000
SUMMARY:Consumer Price Index for September 2026
DESCRIPTION:Official BLS scheduled release; reference period September 2026
END:VEVENT
BEGIN:VEVENT
UID:jolts-2026-09@bls.gov
DTSTART;TZID=America/New_York:20261103T100000
SUMMARY:Job Openings and Labor Turnover Survey for September 2026
END:VEVENT
END:VCALENDAR
"""

BEA_HTML=b"""<html><body><h1>Release Schedule</h1><div>Year 2026</div><table>
<tr><th>Date</th><th>Type</th><th>Release</th></tr>
<tr><td>October 29 8:30 AM</td><td>News</td><td>GDP (Advance Estimate), 3rd Quarter 2026</td></tr>
<tr><td>October 29 8:30 AM</td><td>News</td><td>Personal Income and Outlays, September 2026</td></tr>
</table></body></html>"""

CENSUS_HTML=b"""<html><body><table>
<tr><th>Release</th><th>Date</th><th>Time</th><th>Reference Period</th><th>ID</th></tr>
<tr><td>Advance Monthly Sales for Retail and Food Services</td><td>October 15, 2026</td><td>8:30 AM</td><td>September 2026</td><td>A202610150830</td></tr>
<tr><td>New Residential Construction (Building Permits, Housing Starts, and Housing Completions)</td><td>October 20, 2026</td><td>8:30 AM</td><td>September 2026</td><td>A202610200830</td></tr>
</table></body></html>"""

FOMC_HTML=b"""<html><body><h2>2026 FOMC Meetings</h2>
<div>January 27-28</div><div>Minutes Released February 18</div>
<div>March 17-18*</div><div>Minutes Released April 8</div><div>April 28-29</div>
<div>June 16-17*</div><div>July 28-29</div><div>September 15-16*</div>
<div>October 27-28</div><div>December 8-9*</div>
<h2>2025 FOMC Meetings</h2>
<div>January 28-29</div><div>March 18-19*</div><div>June 17-18*</div>
<div>September 16-17*</div><div>October 28-29</div><div>December 9-10*</div>
</body></html>"""


def test_bls_ics_preserves_exact_release_time_and_uid():
    df=ev.parse_bls_ics(BLS_ICS)
    assert len(df)==2
    cpi=df[df["title"].str.contains("Consumer Price")].iloc[0]
    assert cpi["scheduled_at_et"].startswith("2026-10-14T08:30:00")
    assert cpi["scheduled_at_utc"].startswith("2026-10-14T12:30:00")
    assert cpi["impact"]=="high"
    assert cpi["category"]=="inflation"
    assert cpi["time_known"]


def test_bea_and_census_tables_use_eastern_release_times():
    obs=pd.Timestamp("2026-10-05T12:00:00Z")
    bea=ev.parse_release_table(BEA_HTML,"BEA",obs)
    census=ev.parse_release_table(CENSUS_HTML,"CENSUS",obs)
    assert len(bea)==2 and len(census)==2
    gdp=bea[bea["title"].str.contains("GDP")].iloc[0]
    assert gdp["scheduled_at_et"].startswith("2026-10-29T08:30:00")
    retail=census[census["title"].str.contains("Retail")].iloc[0]
    assert retail["scheduled_at_utc"].startswith("2026-10-15T12:30:00")
    assert retail["reference_period"]=="September 2026"


def test_fomc_calendar_is_date_only_not_invented_2pm():
    df=ev.parse_fomc_html(FOMC_HTML,2026)
    assert len(df)==8
    assert set(df["event_date"])=={
        "2026-01-28","2026-03-18","2026-04-29","2026-06-17",
        "2026-07-29","2026-09-16","2026-10-28","2026-12-09",
    }
    sep=df[df["event_date"]=="2026-09-16"].iloc[0]
    assert sep["scheduled_at_et"] is None
    assert not sep["time_known"]
    assert "statement time not asserted" in sep["timing_basis"]
    assert "SEP meeting" in sep["title"]


def test_schedule_history_retains_reschedule_version(monkeypatch,tmp_path):
    payloads={
        ev.SOURCES["BLS"]:BLS_ICS,
        ev.SOURCES["BEA"]:BEA_HTML,
        ev.SOURCES["CENSUS"]:CENSUS_HTML,
        ev.SOURCES["FOMC"]:FOMC_HTML,
    }
    monkeypatch.setattr(ev,"get_bytes",lambda url: payloads[url])
    cur,hist,status=ev.collect(tmp_path,pd.Timestamp("2026-10-05T12:00:00Z"))
    assert all(status[s]["status"]=="ok" for s in ev.SOURCES)
    old_versions=len(hist)

    payloads[ev.SOURCES["BLS"]]=BLS_ICS.replace(b"20261014T083000",b"20261015T083000")
    cur2,hist2,status2=ev.collect(tmp_path,pd.Timestamp("2026-10-06T12:00:00Z"))
    assert len(hist2)==old_versions+1
    versions=hist2[hist2["stable_id"]=="cpi-2026-09@bls.gov"]
    assert len(versions)==2
    assert versions["event_key"].nunique()==1
    assert versions["schedule_version"].nunique()==2


def test_outputs_are_compact_and_causal(tmp_path):
    obs=pd.Timestamp("2026-10-05T12:00:00Z")
    cur=pd.concat([
        ev.parse_bls_ics(BLS_ICS),
        ev.parse_release_table(BEA_HTML,"BEA",obs),
    ],ignore_index=True)
    cur["observed_at"]=obs.isoformat()
    cur["schedule_version"]=cur.apply(ev._schedule_version,axis=1)
    hist=cur.copy()
    hist["first_seen_at"]=obs.isoformat()
    mp=tmp_path/"manifest.json"; up=tmp_path/"upcoming.json"
    m=ev.build_outputs(cur,hist,{"BLS":{"status":"ok","rows":2},"BEA":{"status":"ok","rows":2}},obs,mp,up)
    assert m["current_events"]==4
    assert m["schedule_versions"]==4
    p=json.loads(up.read_text())
    assert p["timezone"]=="America/New_York"
    assert all("observed_at" not in x for x in p["events"])


BLS_YEAR_HTML=b"""<html><body><h1>Schedule of Selected Releases 2026</h1><table>
<tr><th>Date</th><th>Time</th><th>Release</th></tr>
<tr><td>Friday, November 6, 2026</td><td>08:30 AM</td><td>Employment Situation for October 2026</td></tr>
<tr><td>Tuesday, November 10, 2026</td><td>08:30 AM</td><td>Consumer Price Index for October 2026</td></tr>
<tr><td>Friday, November 13, 2026</td><td>08:30 AM</td><td>Producer Price Index for October 2026</td></tr>
</table></body></html>"""


def test_collect_uses_first_party_bls_html_when_ics_is_blocked(monkeypatch,tmp_path):
    def fake(url):
        if url==ev.SOURCES["BLS"]:
            raise ev.FeedError("HTTP 403")
        if url=="https://www.bls.gov/schedule/2026/":
            return BLS_YEAR_HTML
        if url==ev.SOURCES["BEA"]:
            return BEA_HTML
        if url==ev.SOURCES["CENSUS"]:
            return CENSUS_HTML
        if url==ev.SOURCES["FOMC"]:
            return FOMC_HTML
        raise AssertionError(url)
    monkeypatch.setattr(ev,"get_bytes",fake)
    cur,hist,status=ev.collect(tmp_path,pd.Timestamp("2026-10-05T12:00:00Z"))
    assert status["BLS"]["status"]=="ok"
    assert status["BLS"]["transport"]=="html_fallback"
    bls=cur[cur["source"]=="BLS"]
    assert len(bls)==3
    cpi=bls[bls["title"].str.contains("Consumer Price")].iloc[0]
    assert cpi["scheduled_at_et"].startswith("2026-11-10T08:30:00")
    assert cpi["reference_period"]=="October 2026"


def test_bls_event_identity_is_transport_independent():
    obs=pd.Timestamp("2026-10-05T12:00:00Z")
    html=b"""<html><body><table>
    <tr><th>Date</th><th>Time</th><th>Release</th></tr>
    <tr><td>Wednesday, October 14, 2026</td><td>08:30 AM</td>
        <td>Consumer Price Index for September 2026</td></tr>
    </table></body></html>"""
    ics=ev.parse_bls_ics(BLS_ICS)
    table=ev.parse_release_table(html,"BLS",obs)
    a=ics[ics["title"].str.contains("Consumer Price")].iloc[0]
    b=table[table["title"].str.contains("Consumer Price")].iloc[0]
    assert a["event_key"]==b["event_key"]
    assert a["stable_id"]=="cpi-2026-09@bls.gov"


def test_collect_uses_degraded_official_bls_snapshot_when_live_transports_blocked(monkeypatch,tmp_path):
    def fake(url):
        if url in (ev.SOURCES["BLS"],"https://www.bls.gov/schedule/2026/"):
            raise ev.FeedError("HTTP 403")
        if url==ev.SOURCES["BEA"]:
            return BEA_HTML
        if url==ev.SOURCES["CENSUS"]:
            return CENSUS_HTML
        if url==ev.SOURCES["FOMC"]:
            return FOMC_HTML
        raise AssertionError(url)
    monkeypatch.setattr(ev,"get_bytes",fake)
    cur,hist,status=ev.collect(tmp_path,pd.Timestamp("2026-10-06T01:20:00Z"))
    bls=cur[cur["source"]=="BLS"]
    assert status["BLS"]["status"]=="degraded"
    assert status["BLS"]["transport"]=="official_snapshot"
    assert status["BLS"]["snapshot_as_of"]==ev.BLS_SNAPSHOT_CAPTURED_AT
    assert len(bls)==len(ev.BLS_SNAPSHOT_2026)
    cpi=bls[(bls["event_date"]=="2026-10-14") & bls["title"].str.contains("Consumer Price")].iloc[0]
    assert cpi["scheduled_at_et"].startswith("2026-10-14T08:30:00")
    assert cpi["scheduled_at_utc"].startswith("2026-10-14T12:30:00")
    assert cpi["reference_period"]=="September 2026"
    assert "HTTP 403" in status["BLS"]["error"]


def test_bls_snapshot_does_not_claim_other_years():
    assert not ev.bls_official_snapshot(2027).shape[0]


def test_schedule_history_sanitizer_removes_only_impossible_fomc_spill_rows():
    df=pd.DataFrame([
        {"source":"FOMC","stable_id":"2026-meeting-1","event_date":"2026-01-28"},
        {"source":"FOMC","stable_id":"2026-meeting-8","event_date":"2026-12-09"},
        {"source":"FOMC","stable_id":"2026-meeting-9","event_date":"2026-10-29"},
        {"source":"FOMC","stable_id":"2026-meeting-46","event_date":"2026-12-18"},
        {"source":"BEA","stable_id":None,"event_date":"2026-10-29"},
    ])
    clean,removed=ev._sanitize_schedule_history(df)
    assert removed==2
    assert set(clean["stable_id"].dropna())=={"2026-meeting-1","2026-meeting-8"}
    assert (clean["source"]=="BEA").sum()==1
