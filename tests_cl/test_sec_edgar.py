import pandas as pd
from cl_lab.feeds import sec_edgar as sec


def test_acceptance_timestamp_never_invents_timezone():
    assert pd.isna(sec._accepted("2026-10-05T12:34:56.000"))
    ts=sec._accepted("2026-10-05T12:34:56.000Z")
    assert ts.tz is not None
    assert ts.isoformat().startswith("2026-10-05T12:34:56")


def test_recent_rows_filters_forms_and_preserves_acceptance_time():
    payload={"filings":{"recent":{
        "form":["10-Q","S-8","8-K"],
        "accessionNumber":["a","b","c"],
        "filingDate":["2026-08-01","2026-08-02","2026-08-03"],
        "reportDate":["2026-06-30","","2026-08-03"],
        "acceptanceDateTime":["2026-08-01T12:00:00.000Z","2026-08-02T12:00:00.000Z","2026-08-03T13:30:00.000Z"],
        "primaryDocument":["q.htm","s8.htm","8k.htm"],
        "primaryDocDescription":["10-Q","","8-K"],
        "items":["","","2.02"],
        "fileNumber":["1","2","1"],
    }}}
    rows=sec._recent_rows(payload,"AAPL","0000320193")
    assert [r["form"] for r in rows]==["10-Q","8-K"]
    assert rows[0]["accepted_at"].isoformat().startswith("2026-08-01T12:00:00")


def test_companyfacts_uses_accession_acceptance_time(monkeypatch):
    payload={"facts":{"us-gaap":{"NetIncomeLoss":{"units":{"USD":[
        {"val":100,"start":"2026-01-01","end":"2026-03-31","filed":"2026-04-20",
         "form":"10-Q","fy":2026,"fp":"Q1","accn":"x1"}
    ]}}}}}
    monkeypatch.setattr(sec,"_get",lambda url: payload)
    accepted=pd.Timestamp("2026-04-20T20:01:02Z")
    df=sec.companyfacts_for_ticker("AAPL","0000320193",{"x1":accepted})
    assert len(df)==1
    assert df.iloc[0]["concept"]=="NetIncomeLoss"
    assert df.iloc[0]["accepted_at"]==accepted


def test_refresh_tracks_partial_status_without_losing_good_ticker(monkeypatch,tmp_path):
    monkeypatch.setattr(sec,"ticker_map",lambda:{"AAA":"0000000001","BBB":"0000000002"})
    good=pd.DataFrame([{
        "ticker":"AAA","cik":"0000000001","form":"10-Q","accession":"a",
        "filing_date":pd.Timestamp("2026-08-01"),"report_date":pd.Timestamp("2026-06-30"),
        "acceptance_datetime_raw":"2026-08-01T12:00:00Z",
        "accepted_at":pd.Timestamp("2026-08-01T12:00:00Z"),
        "primary_document":"q.htm","primary_doc_description":"10-Q","items":"","file_number":"1",
    }])
    def filings(ticker,cik,max_history_files=8):
        if ticker=="BBB":
            raise RuntimeError("temporary")
        return good
    monkeypatch.setattr(sec,"filings_for_ticker",filings)
    monkeypatch.setattr(sec,"companyfacts_for_ticker",lambda *a,**k: pd.DataFrame())
    f,x,status=sec.refresh(tmp_path,("AAA","BBB"))
    assert len(f)==1 and x.empty
    assert status["AAA"]["status"]=="ok"
    assert status["BBB"]["status"]=="error"


def test_sec_http_does_not_request_compressed_bytes(monkeypatch):
    seen={}
    monkeypatch.setenv("SEC_USER_AGENT","ICARUS Research contact@example.com")
    monkeypatch.setattr(sec.time,"sleep",lambda *_: None)
    monkeypatch.setattr(sec,"_last_request",0.0)
    def fake(url,headers=None,**kwargs):
        seen.update(headers or {})
        return b'{}'
    monkeypatch.setattr(sec,"get_bytes",fake)
    sec._get("https://data.sec.gov/test.json")
    assert "Accept-Encoding" not in seen
    assert seen["Accept"]=="application/json"


def test_refresh_seeds_history_once_then_recent_only(monkeypatch,tmp_path):
    monkeypatch.setattr(sec,"ticker_map",lambda:{"AAA":"0000000001"})
    calls=[]
    def filing_frame(accession):
        return pd.DataFrame([{
            "ticker":"AAA","cik":"0000000001","form":"10-Q","accession":accession,
            "filing_date":pd.Timestamp("2026-08-01"),"report_date":pd.Timestamp("2026-06-30"),
            "acceptance_datetime_raw":"2026-08-01T12:00:00Z",
            "accepted_at":pd.Timestamp("2026-08-01T12:00:00Z"),
            "primary_document":"q.htm","primary_doc_description":"10-Q","items":"","file_number":"1",
        }])
    def filings(ticker,cik,max_history_files=8):
        calls.append(max_history_files)
        return filing_frame("seed" if max_history_files else "recent")
    monkeypatch.setattr(sec,"filings_for_ticker",filings)
    monkeypatch.setattr(sec,"companyfacts_for_ticker",lambda *a,**k: pd.DataFrame())
    sec.refresh(tmp_path,("AAA",))
    sec.refresh(tmp_path,("AAA",))
    assert calls==[8,0]
    cached=pd.read_csv(tmp_path/"sec_edgar"/"filings.csv.gz",compression="gzip")
    assert set(cached["accession"])=={"seed","recent"}


def test_ticker_map_falls_back_to_default_ciks_when_sec_www_is_blocked(monkeypatch):
    def blocked(url):
        raise RuntimeError("403")
    monkeypatch.setattr(sec,"_get",blocked)
    mapping=sec.ticker_map()
    assert mapping["NVDA"]=="0001045810"
    assert mapping["AAPL"]=="0000320193"
    assert mapping["GOOGL"]=="0001652044"
    assert set(sec.DEFAULT_TICKERS) <= set(mapping)


def test_ticker_map_remote_data_can_extend_default_seed(monkeypatch):
    monkeypatch.setattr(sec,"_get",lambda url: {
        "0":{"ticker":"NVDA","cik_str":1045810},
        "1":{"ticker":"AMD","cik_str":2488},
    })
    mapping=sec.ticker_map()
    assert mapping["NVDA"]=="0001045810"
    assert mapping["AMD"]=="0000002488"


def test_user_agent_is_required(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT",raising=False)
    try:
        sec._ua()
        assert False, "missing SEC_USER_AGENT should fail"
    except Exception as e:
        assert "SEC_USER_AGENT is required" in str(e)


def test_refresh_all_failures_return_diagnostics(monkeypatch,tmp_path):
    monkeypatch.setattr(sec,"ticker_map",lambda:{"AAA":"0000000001","BBB":"0000000002"})
    monkeypatch.setattr(sec,"filings_for_ticker",lambda *a,**k: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(sec,"companyfacts_for_ticker",lambda *a,**k: pd.DataFrame())
    filings,facts,status=sec.refresh(tmp_path,("AAA","BBB"))
    assert filings.empty and facts.empty
    assert status["AAA"]["status"]=="error"
    assert "blocked" in status["AAA"]["error"]
    assert status["BBB"]["status"]=="error"
