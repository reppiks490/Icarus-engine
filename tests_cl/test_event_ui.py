import json

import pandas as pd

from cl_lab import run


def test_economic_events_ui_keeps_exact_countdowns_and_date_only_events(tmp_path):
    manifest={
        "generated_at":"2026-10-05T20:00:00+00:00",
        "sources":{
            "BLS":{"status":"ok","rows":120,"transport":"html_fallback"},
            "BEA":{"status":"ok","rows":63},
            "CENSUS":{"status":"ok","rows":159},
            "FOMC":{"status":"ok","rows":8},
        },
        "current_events":350,
        "schedule_versions":351,
        "high_impact_current":150,
        "time_known_current":342,
        "causality":"use only schedule versions known by decision time",
    }
    upcoming={"events":[
        {
            "source":"BLS","event_key":"past","title":"Past CPI","category":"inflation","impact":"high",
            "event_date":"2026-10-05","scheduled_at_et":"2026-10-05T08:30:00-04:00",
            "scheduled_at_utc":"2026-10-05T12:30:00+00:00","time_known":True,"timing_basis":"source_schedule",
        },
        {
            "source":"BLS","event_key":"jobs","title":"Employment Situation","category":"labor","impact":"high",
            "reference_period":"September 2026","event_date":"2026-10-06",
            "scheduled_at_et":"2026-10-06T08:30:00-04:00",
            "scheduled_at_utc":"2026-10-06T12:30:00+00:00","time_known":True,"timing_basis":"source_schedule",
        },
        {
            "source":"FOMC","event_key":"fomc","title":"FOMC policy decision","category":"policy","impact":"high",
            "event_date":"2026-10-28","scheduled_at_et":None,"scheduled_at_utc":None,
            "time_known":False,"timing_basis":"meeting_end_date; statement time not asserted",
        },
    ]}
    (tmp_path/"economic_events_manifest.json").write_text(json.dumps(manifest))
    (tmp_path/"economic_events_upcoming.json").write_text(json.dumps(upcoming))

    out=run._economic_events_ui(tmp_path,pd.Timestamp("2026-10-06T11:00:00Z"))
    assert out["status"]=="ok"
    assert out["next_high_impact"]["event_key"]=="jobs"
    assert out["next_high_impact"]["minutes_to_event"]==90.0
    assert out["high_impact_within_24h"]==1
    assert [x["event_key"] for x in out["upcoming"]]==["jobs","fomc"]
    fomc=out["upcoming"][1]
    assert fomc["minutes_to_event"] is None
    assert fomc["time_known"] is False
    assert "statement time not asserted" in fomc["timing_basis"]
    assert out["source_status"]["BLS"]["transport"]=="html_fallback"


def test_economic_events_ui_is_explicit_when_clock_missing(tmp_path):
    out=run._economic_events_ui(tmp_path,pd.Timestamp("2026-10-06T11:00:00Z"))
    assert out["status"]=="UNAVAILABLE"
    assert "has not produced" in out["reason"]
