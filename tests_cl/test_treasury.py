import json
import numpy as np
import pandas as pd

from cl_lab.feeds import registry, treasury


def test_parse_operating_cash_preserves_dates_text_and_numbers():
    rows=[{
        "record_date":"2026-10-01",
        "account_type":"Federal Reserve Account",
        "close_today_bal":"812345",
        "open_today_bal":"800000",
        "src_line_nbr":"1",
    }]
    df=treasury.parse_records(rows,"operating_cash")
    assert str(df.index[0].date())=="2026-10-01"
    assert df.iloc[0]["account_type"]=="Federal Reserve Account"
    assert float(df.iloc[0]["close_today_bal"])==812345.0


def test_fiscal_api_paginates_and_uses_incremental_filter(monkeypatch):
    calls=[]
    def fake_get(url,params=None,**kwargs):
        calls.append((url,dict(params)))
        page=int(params["page[number]"])
        data=([{"record_date":"2026-09-30","account_type":"A","close_today_bal":"100","src_line_nbr":"1"},
               {"record_date":"2026-10-01","account_type":"A","close_today_bal":"110","src_line_nbr":"1"}]
              if page==1 else [])
        return json.dumps({"data":data,"meta":{"total-pages":1}}).encode()
    monkeypatch.setattr(treasury,"get_bytes",fake_get)
    df=treasury.fetch_dataset("operating_cash",since="2026-09-01",page_size=2)
    assert len(df)==2
    assert calls[0][1]["filter"]=="record_date:gte:2026-09-01"
    assert calls[0][1]["page[size]"]==2


def test_operating_cash_features_and_revision_merge(monkeypatch):
    old=pd.DataFrame(
        {"account_type":["A","A"],"close_today_bal":[100.0,110.0],"src_line_nbr":[1,1],"dataset":["operating_cash"]*2},
        index=pd.to_datetime(["2026-09-29","2026-09-30"]),
    )
    old.index.name="date"
    fresh=pd.DataFrame(
        {"account_type":["A","A"],"close_today_bal":[112.0,120.0],"src_line_nbr":[1,1],"dataset":["operating_cash"]*2},
        index=pd.to_datetime(["2026-09-30","2026-10-01"]),
    )
    fresh.index.name="date"
    seen={}
    def fake_fetch(dataset,since=None,**kwargs):
        seen["since"]=since
        return fresh
    monkeypatch.setattr(treasury,"fetch_dataset",fake_fetch)
    out,note=treasury.refresh(old,"operating_cash")
    assert float(out.loc[pd.Timestamp("2026-09-30"),"close_today_bal"])==112.0
    assert float(out.loc[pd.Timestamp("2026-10-01"),"feature_cash_1d_change"])==8.0
    assert seen["since"]==pd.Timestamp("2026-08-26")
    assert "revision_window_start=2026-08-26" in note


def test_auction_bid_to_cover_feature_is_term_local():
    dates=pd.date_range("2026-01-01",periods=6,freq="7D")
    df=pd.DataFrame({
        "security_term":["10-Year"]*6,
        "bid_to_cover_ratio":[2.0,2.1,2.2,2.3,2.4,3.0],
        "cusip":[f"X{i}" for i in range(6)],
        "dataset":["auctions"]*6,
    },index=dates)
    df.index.name="date"
    out=treasury.derive_features(df,"auctions")
    assert np.isnan(out["feature_bid_to_cover_z20"].iloc[0])
    assert out["feature_bid_to_cover_z20"].iloc[-1] > 0


def test_treasury_feeds_registered():
    names={f["name"] for f in registry.FEEDS}
    assert {"treasury_operating_cash","treasury_auctions","treasury_debt_to_penny"} <= names


def test_treasury_panel_integrity_uses_dataset_identity():
    df=pd.DataFrame({
        "account_type":["A","B","A"],
        "src_line_nbr":[1,1,1],
        "close_today_bal":[100.0,200.0,110.0],
    },index=pd.to_datetime(["2026-10-01","2026-10-01","2026-10-02"]))
    df.index.name="date"
    rep=treasury.panel_integrity(df,"operating_cash")
    assert rep["rows"]==3
    assert rep["dates"]==2
    assert rep["duplicate_records"]==0

    dup=pd.concat([df,df.iloc[[0]]])
    rep2=treasury.panel_integrity(dup,"operating_cash")
    assert rep2["duplicate_records"]==1


def test_treasury_auction_integrity_allows_same_date_different_cusips():
    df=pd.DataFrame({
        "cusip":["A","B"],
        "security_term":["2-Year","5-Year"],
    },index=pd.to_datetime(["2026-10-01","2026-10-01"]))
    df.index.name="date"
    rep=treasury.panel_integrity(df,"auctions")
    assert rep["duplicate_records"]==0
    assert rep["dates"]==1
