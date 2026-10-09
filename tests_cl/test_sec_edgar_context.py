import pandas as pd

from cl_lab.feeds import sec_edgar as sec


def test_research_context_preserves_causal_filing_time_and_latest_fact_values():
    filings = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "cik": "0000000001",
                "form": "10-Q",
                "accession": "old",
                "filing_date": pd.Timestamp("2026-05-01"),
                "report_date": pd.Timestamp("2026-03-31"),
                "accepted_at": pd.Timestamp("2026-05-01T20:00:00Z"),
                "items": "",
            },
            {
                "ticker": "AAA",
                "cik": "0000000001",
                "form": "8-K",
                "accession": "new",
                "filing_date": pd.Timestamp("2026-10-08"),
                "report_date": pd.Timestamp("2026-10-08"),
                "accepted_at": pd.Timestamp("2026-10-08T21:12:13Z"),
                "items": "2.02",
            },
        ]
    )
    facts = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "concept": "Revenues",
                "unit": "USD",
                "value": 100,
                "accession": "old",
                "accepted_at": pd.Timestamp("2026-05-01T20:00:00Z"),
                "end": pd.Timestamp("2026-03-31"),
                "form": "10-Q",
            },
            {
                "ticker": "AAA",
                "concept": "Revenues",
                "unit": "USD",
                "value": 125,
                "accession": "new",
                "accepted_at": pd.Timestamp("2026-10-08T21:12:13Z"),
                "end": pd.Timestamp("2026-09-30"),
                "form": "10-Q",
            },
        ]
    )
    status = {"AAA": {"status": "ok", "cik": "0000000001", "filings": 2, "facts": 2}}

    context = sec.research_context(filings, facts, status)

    assert context["schema"] == "icarus.sec_edgar.research_context/1"
    assert context["authority"] == "RESEARCH_CONTEXT_ONLY"
    assert context["execution_authorized"] is False
    assert context["production_decision_authorized"] is False
    assert context["causality"] == "accepted_at is the availability timestamp; report/end dates never grant earlier availability"
    latest = context["tickers"]["AAA"]["latest_filing"]
    assert latest["accession"] == "new"
    assert latest["accepted_at"] == "2026-10-08T21:12:13+00:00"
    revenue = context["tickers"]["AAA"]["latest_facts"]["Revenues|USD"]
    assert revenue["value"] == 125
    assert revenue["accepted_at"] == "2026-10-08T21:12:13+00:00"


def test_research_context_drops_facts_without_known_acceptance_time():
    filings = pd.DataFrame()
    facts = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "concept": "Assets",
                "unit": "USD",
                "value": 999,
                "accession": "x",
                "accepted_at": pd.NaT,
                "end": pd.Timestamp("2026-09-30"),
                "form": "10-Q",
            }
        ]
    )
    context = sec.research_context(filings, facts, {"AAA": {"status": "ok"}})
    assert context["tickers"]["AAA"]["latest_facts"] == {}
