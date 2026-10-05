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
