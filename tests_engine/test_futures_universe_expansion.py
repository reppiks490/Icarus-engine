from __future__ import annotations

from pathlib import Path

import pytest

from icarus_engine.assets import REGISTRY, resolve


# symbol: ticker, mintick, multiplier, exchange, asset_class, micro_of, session
EXPECTED = {
    # Existing micros that must be true first-class futures, not parent aliases / spot fallthroughs.
    "MNQ": ("MNQ=F", 0.25, 2.0, "CME", "equity_index", "NQ", "rth"),
    "MES": ("MES=F", 0.25, 5.0, "CME", "equity_index", "ES", "rth"),
    "MYM": ("MYM=F", 1.0, 0.5, "CBOT", "equity_index", "YM", "rth"),
    "MGC": ("MGC=F", 0.10, 10.0, "COMEX", "metal", "GC", "rth"),
    "SIL": ("SIL=F", 0.005, 1000.0, "COMEX", "metal", "SI", "rth"),
    # Handpicked expansion.
    "RTY": ("RTY=F", 0.10, 50.0, "CME", "equity_index", None, "rth"),
    "M2K": ("M2K=F", 0.10, 5.0, "CME", "equity_index", "RTY", "rth"),
    "CL": ("CL=F", 0.01, 1000.0, "NYMEX", "energy", None, "eth"),
    "MCL": ("MCL=F", 0.01, 100.0, "NYMEX", "energy", "CL", "eth"),
    "NG": ("NG=F", 0.001, 10000.0, "NYMEX", "energy", None, "eth"),
    "MNG": ("MNG=F", 0.001, 1000.0, "NYMEX", "energy", "NG", "eth"),
    "HG": ("HG=F", 0.0005, 25000.0, "COMEX", "metal", None, "eth"),
    "MHG": ("MHG=F", 0.0005, 2500.0, "COMEX", "metal", "HG", "eth"),
    "6E": ("6E=F", 0.00005, 125000.0, "CME", "fx", None, "eth"),
    "M6E": ("M6E=F", 0.0001, 12500.0, "CME", "fx", "6E", "eth"),
    "6J": ("6J=F", 0.0000005, 12500000.0, "CME", "fx", None, "eth"),
    "MJY": ("MJY=F", 0.000001, 1250000.0, "CME", "fx", "6J", "eth"),
    "6B": ("6B=F", 0.0001, 62500.0, "CME", "fx", None, "eth"),
    "M6B": ("M6B=F", 0.0001, 6250.0, "CME", "fx", "6B", "eth"),
    "6A": ("6A=F", 0.00005, 100000.0, "CME", "fx", None, "eth"),
    "M6A": ("M6A=F", 0.0001, 10000.0, "CME", "fx", "6A", "eth"),
    "ZN": ("ZN=F", 0.015625, 1000.0, "CBOT", "rates", None, "eth"),
    "ZB": ("ZB=F", 0.03125, 1000.0, "CBOT", "rates", None, "eth"),
}


def test_expansion_and_existing_micros_are_first_class_futures():
    missing = sorted(set(EXPECTED) - set(REGISTRY))
    assert not missing, f"missing first-class futures: {missing}"

    for symbol, expected in EXPECTED.items():
        ticker, mintick, multiplier, exchange, asset_class, micro_of, session = expected
        spec = REGISTRY[symbol]
        assert spec.symbol == symbol
        assert spec.kind == "futures"
        assert spec.feed == "yahoo"
        assert spec.ticker == ticker
        assert spec.mintick == pytest.approx(mintick)
        assert spec.multiplier == pytest.approx(multiplier)
        assert spec.exchange == exchange
        assert spec.asset_class == asset_class
        assert spec.micro_of == micro_of
        assert spec.session == session
        assert spec.tv_symbol
        assert spec.feed_mode == "public_delayed"


def test_micro_resolution_never_collapses_to_parent_or_coinbase():
    for symbol in ("MNQ", "MES", "MYM", "MGC", "SIL", "M2K", "MCL", "MNG", "MHG", "M6E", "MJY", "M6B", "M6A"):
        spec = resolve(symbol)
        assert spec.symbol == symbol
        assert spec.kind == "futures"
        assert spec.feed == "yahoo"

    assert resolve("MNQ").multiplier == pytest.approx(2.0)
    assert resolve("MES").multiplier == pytest.approx(5.0)
    assert resolve("MYM").multiplier == pytest.approx(0.5)


def test_continuous_aliases_resolve_to_the_correct_contract_size():
    aliases = {
        "MNQ1!": "MNQ", "MES1!": "MES", "MYM1!": "MYM", "MGC1!": "MGC", "SIL1!": "SIL",
        "RTY1!": "RTY", "M2K1!": "M2K", "CL1!": "CL", "MCL1!": "MCL",
        "NG1!": "NG", "MNG1!": "MNG", "HG1!": "HG", "MHG1!": "MHG",
        "6E1!": "6E", "M6E1!": "M6E", "6J1!": "6J", "MJY1!": "MJY",
        "6B1!": "6B", "M6B1!": "M6B", "6A1!": "6A", "M6A1!": "M6A",
        "ZN1!": "ZN", "ZB1!": "ZB",
    }
    for alias, symbol in aliases.items():
        assert resolve(alias).symbol == symbol


def test_expansion_tickers_are_unique_and_micro_links_are_valid():
    specs = [REGISTRY[s] for s in EXPECTED]
    tickers = [s.ticker for s in specs]
    assert len(tickers) == len(set(tickers))
    for spec in specs:
        if spec.micro_of:
            assert spec.micro_of in REGISTRY
            parent = REGISTRY[spec.micro_of]
            assert parent.kind == "futures"
            assert spec.multiplier < parent.multiplier


def test_api_and_dashboard_are_registry_driven():
    root = Path(__file__).parents[1]
    server = (root / "icarus_engine" / "server.py").read_text(encoding="utf-8")
    html = (root / "icarus_engine" / "dashboard.html").read_text(encoding="utf-8")
    assert 'p.path == "/api/assets"' in server
    assert "for s in REGISTRY.values()" in server
    for field in ("symbol", "name", "feed", "calendar", "mintick", "multiplier", "kind"):
        assert f'"{field}"' in server
    assert "fetch('/api/assets')" in html or 'fetch("/api/assets")' in html
    assert "REGISTRY.map" in html
    assert "Registry:" in html


def test_public_no_secret_probe_contract_exists_and_covers_expansion():
    probe = Path(__file__).parents[1] / "tools" / "futures_universe_probe.py"
    assert probe.exists(), "no-cost futures provider probe is missing"
    text = probe.read_text(encoding="utf-8")
    assert "PROBE_SYMBOLS" in text
    for symbol in EXPECTED:
        assert repr(symbol) in text or f'"{symbol}"' in text
    assert "json" in text
    assert "Yahoo" in text
    assert "API_KEY" not in text
    assert "SECRET" not in text


def test_research_document_records_selection_and_live_arming_boundary():
    doc = Path(__file__).parents[1] / "docs" / "FUTURES_UNIVERSE_2026_10_16.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for symbol in ("RTY", "CL", "NG", "HG", "6E", "6J", "6B", "6A", "ZN", "ZB"):
        assert symbol in text
    assert "live broker arming" in text.lower()
    assert "disabled" in text.lower()
    assert "delayed" in text.lower()
