import hashlib
from pathlib import Path

from icarus_engine.private_history import (
    KNOWN_PRIVATE_EXPORTS,
    discover_private_history,
    safe_private_label,
)


def test_known_nq_eth_catalog_entries_are_exact_and_private():
    std=KNOWN_PRIVATE_EXPORTS["a8141ffa372b4ffaba4d6bf8b8998a489f2daf00bfad5e248bf27132d99f0932"]
    ha=KNOWN_PRIVATE_EXPORTS["4fe26a9b2ee9a5e81c24577f2abd51073e7e944f4f6aa43a77b61095af44e48c"]
    assert std["symbol"]=="NQ" and std["tf_minutes"]==20 and std["session"]=="eth"
    assert std["price_geometry"]=="standard" and std["rows"]==41239
    assert ha["price_geometry"]=="heikin_ashi" and ha["rows"]==41239


def test_private_history_discovery_requires_hash_and_session_match(tmp_path):
    p=tmp_path/"CME_MINI_DL_NQ1!, 20.csv"
    p.write_text("time,open,high,low,close\n60,1,2,0.5,1.5\n",encoding="utf-8")
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    catalog={digest:{
        "symbol":"NQ","tf_minutes":20,"session":"eth","price_geometry":"standard",
        "rows":1,"first_ts":60,"last_ts":60,"source":"test"
    }}
    hit=discover_private_history("NQ",20,"eth","standard",roots=[str(tmp_path)],catalog=catalog)
    assert hit is not None
    assert hit["sha256"]==digest and hit["classification"]=="EXACT_OPERATOR_HISTORY"
    assert hit["private"] is True and hit["execution_authorized"] is False
    assert discover_private_history("NQ",20,"rth","standard",roots=[str(tmp_path)],catalog=catalog) is None
    assert discover_private_history("NQ",20,"eth","heikin_ashi",roots=[str(tmp_path)],catalog=catalog) is None


def test_private_history_safe_label_does_not_expose_directory(tmp_path):
    p=tmp_path/"CME_MINI_DL_NQ1!, 20.csv"
    meta={"display_name":p.name,"sha256":"a"*64}
    label=safe_private_label(meta)
    assert label.startswith("private:CME_MINI_DL_NQ1!")
    assert str(tmp_path) not in label
    assert label.endswith("#aaaaaaaaaaaa")


def test_runtime_prefers_private_exact_and_ui_redacts_path():
    rt=Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    gate=Path("icarus_engine/completion_gate.py").read_text(encoding="utf-8")
    ui=Path("icarus_engine/assurance-ui.js").read_text(encoding="utf-8")
    assert "discover_private_history(" in rt
    assert 'source_sets.append(("private_exact"' in rt
    assert '"warmup_private_history"' in rt
    assert '("exact","private_exact")' in gate
    assert "Private exact source:" in ui
    assert "Raw licensed files remain outside Git." in ui


def test_raw_private_history_folder_is_gitignored():
    gi=Path(".gitignore").read_text(encoding="utf-8")
    assert "private_history/" in gi


def test_tradingview_export_schema_loads_without_volume(tmp_path):
    from icarus_engine.history_v2 import load_csv
    p=tmp_path/"CME_MINI_DL_NQ1!, 20.csv"
    p.write_text(
        "time,open,high,low,close,RATE ST,Long,Short\n"
        "1717365600,18590.25,18598.5,18539.25,18577,19000,0,0\n",
        encoding="utf-8")
    bars,report=load_csv(str(p),1200,"eth")
    assert report.rows_read==1 and report.bars_valid==1 and report.rejected==0
    assert bars[0].ts==1717365600 and bars[0].v==0.0
