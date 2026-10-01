import hashlib
from pathlib import Path

from icarus_engine.private_history import (
    KNOWN_PRIVATE_REPORTS,
    discover_private_reference_reports,
)


def test_known_rth_reports_preserve_2019_reference_metadata():
    standard=KNOWN_PRIVATE_REPORTS["05cebeb4a44fcad254b6c7ee05d66ef8a81593e5d984cf91b5ee1b1a8dd9aae3"]
    ha=KNOWN_PRIVATE_REPORTS["dc3c1c3b32bc7da97bcbaa5bd207eb1d462d8104cc77b9f4e5cb75eef9425585"]
    assert standard["symbol"]=="NQ" and standard["tf_minutes"]==20 and standard["session"]=="rth"
    assert standard["price_geometry"]=="standard"
    assert standard["trading_range"].startswith("Feb 7, 2019")
    assert standard["closed_trades"]==473 and standard["net_profit_usd"]==56950.0
    assert standard["max_drawdown_intrabar_usd"]==80846.0
    assert ha["price_geometry"]=="heikin_ashi"
    assert ha["closed_trades"]==1204 and ha["net_profit_usd"]==967652.0
    assert ha["max_drawdown_intrabar_usd"]==60844.0


def test_reference_report_discovery_verifies_hash_without_exposing_path(tmp_path):
    p=tmp_path/"THE_PULSE_OF_ICARUS_CME_MINI_NQ1!_fixture.xlsx"
    p.write_bytes(b"private-report-fixture")
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    catalog={digest:{
        "symbol":"NQ","tf_minutes":20,"session":"rth","price_geometry":"standard",
        "chart_type":"Candles","canonical_name":"fixture.xlsx",
        "trading_range":"2019 to 2026","closed_trades":1,
        "classification":"EXACT_OPERATOR_STRATEGY_REPORT",
    }}
    rows=discover_private_reference_reports("NQ",20,"rth",roots=[str(tmp_path)],catalog=catalog)
    assert len(rows)==1
    row=rows[0]
    assert row["local_file_verified"] is True
    assert row["sha256"]==digest
    assert row["warmup_eligible"] is False
    assert row["data_type"]=="STRATEGY_REPORT_NOT_BAR_HISTORY"
    assert row["execution_authorized"] is False
    assert "path" not in row


def test_reference_report_catalog_still_surfaces_when_local_file_is_absent(tmp_path):
    rows=discover_private_reference_reports(
        "NQ",20,"rth",roots=[str(tmp_path)],
        catalog={"a"*64:{
            "symbol":"NQ","tf_minutes":20,"session":"rth","price_geometry":"standard",
            "canonical_name":"report.xlsx","classification":"EXACT_OPERATOR_STRATEGY_REPORT",
        }})
    assert len(rows)==1
    assert rows[0]["local_file_verified"] is False
    assert rows[0]["warmup_eligible"] is False


def test_runtime_and_ui_surface_reference_reports_without_using_them_for_warmup():
    rt=Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    ui=Path("icarus_engine/assurance-ui.js").read_text(encoding="utf-8")
    assert "discover_private_reference_reports(" in rt
    assert '"private_reference_reports":' in rt
    assert "Long-history RTH report witnesses" in ui
    assert "not raw bar history" in ui
    assert 'source_sets.append(("private_report"' not in rt
