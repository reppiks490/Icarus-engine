import pandas as pd
from cl_lab.feeds import fred_alfred as fa

def test_point_in_time_uses_closed_realtime_window(monkeypatch):
    seen={}
    def fake(endpoint,key,**params):
        seen.update(params)
        return {"observations":[{"date":"2020-01-01","realtime_start":"2020-02-01","realtime_end":"2020-02-29","value":"1.5"}]}
    monkeypatch.setattr(fa,"_get",fake)
    df=fa.point_in_time("CPIAUCSL","k","2020-02-15")
    assert seen["realtime_start"]=="2020-02-15"
    assert seen["realtime_end"]=="2020-02-15"
    assert df.iloc[0]["value"]==1.5

def test_missing_values_are_not_future_filled(monkeypatch):
    monkeypatch.setattr(fa,"_get",lambda *a,**k: {"observations":[
        {"date":"2020-01-01","realtime_start":"2020-02-01","realtime_end":"9999-12-31","value":"."},
        {"date":"2020-02-01","realtime_start":"2020-03-01","realtime_end":"9999-12-31","value":"2.0"}]})
    df=fa.observations("X","k")
    assert pd.isna(df.iloc[0]["value"]) and df.iloc[1]["value"]==2.0

def test_catalog_has_orthogonal_families_and_vintage_sensitive_series():
    assert {"rates","liquidity","credit","inflation","labor","growth","risk"} <= set(fa.SERIES)
    assert {"CPIAUCSL","PAYEMS","UNRATE","GDPC1"} <= fa.VINTAGE_SERIES
    assert len({x for ids in fa.SERIES.values() for x in ids}) >= 35


def test_manifest_validation_rejects_empty_rows_and_missing_vintages():
    m={"series":{
        "DGS10":{"status":"ok","rows":10},
        "CPIAUCSL":{"status":"ok","rows":10,"vintage_dates":0},
        "PAYEMS":{"status":"error","rows":0},
    }}
    bad=fa.validate_manifest(m)
    assert bad==["CPIAUCSL","PAYEMS"]

def test_manifest_validation_accepts_real_rows_and_vintages():
    m={"series":{
        "DGS10":{"status":"ok","rows":10},
        "CPIAUCSL":{"status":"ok","rows":10,"vintage_dates":5},
    }}
    assert fa.validate_manifest(m)==[]


def test_point_in_time_date_is_fred_calendar_not_utc():
    # 00:25 UTC on 10-11 is still 10-10 in FRED's US Central calendar; asking for 10-11 is "the future"
    assert fa.fred_today("2026-10-11T00:25:00Z") == "2026-10-10"
    assert fa.fred_today("2026-10-11T12:00:00Z") == "2026-10-11"


def test_refresh_requests_vintages_as_of_fred_today(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(fa, "SERIES", {"inflation": ["CPIAUCSL"]})
    monkeypatch.setattr(fa, "observations", lambda sid, key, **p: (asked.append(p.get("realtime_start")) or
                        pd.DataFrame([{"series_id": sid, "observation_date": "2026-08-01", "value": 1.0}])))
    monkeypatch.setattr(fa, "vintage_dates", lambda sid, key: ["2026-09-11"])
    man = fa.refresh(tmp_path, "k", now="2026-10-11T00:25:00Z")
    assert man["series"]["CPIAUCSL"]["status"] == "ok"
    assert "2026-10-10" in asked and "2026-10-11" not in asked
