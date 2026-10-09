from __future__ import annotations

import csv
import gzip
from pathlib import Path

from tools.databento_depth_research_context import build_context


def _write_slice(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_build_context_consumes_actual_depth_features_and_is_research_only(tmp_path: Path):
    depth = tmp_path / ".databento_depth_cache"
    _write_slice(
        depth / "features" / "secondary" / "mbo" / "nq" / "2026-10-01.csv.gz",
        [
            {"ts_minute": "2026-10-01T13:30:00+00:00", "events": "100", "add_events": "60", "cancel_events": "30", "trade_events": "10", "spread_mean": "0.25", "depth10_bid_mean": "120", "depth10_ask_mean": "80", "event_size_imbalance": "0.20", "cancel_add_size_ratio": "0.50", "latency_mean_ns": "1000"},
            {"ts_minute": "2026-10-01T13:31:00+00:00", "events": "200", "add_events": "100", "cancel_events": "80", "trade_events": "20", "spread_mean": "0.50", "depth10_bid_mean": "90", "depth10_ask_mean": "110", "event_size_imbalance": "-0.10", "cancel_add_size_ratio": "0.80", "latency_mean_ns": "2000"},
        ],
    )
    _write_slice(
        depth / "features" / "third" / "mbp10" / "zn" / "2026-09-30.csv.gz",
        [
            {"ts_minute": "2026-09-30T14:00:00+00:00", "events": "50", "add_events": "0", "cancel_events": "0", "trade_events": "5", "spread_mean": "0.015625", "depth10_bid_mean": "500", "depth10_ask_mean": "500", "event_size_imbalance": "0", "cancel_add_size_ratio": "", "latency_mean_ns": "1500"},
        ],
    )

    context = build_context(tmp_path, depth)

    assert context["authority"] == "RESEARCH_CONTEXT_ONLY"
    assert context["raw_payloads_included"] is False
    assert context["raw_dbn_retained"] is False
    assert context["candidate_evidence_eligible"] is False
    assert context["execution_authorized"] is False
    assert context["production_decision_authorized"] is False
    assert context["automatic_model_promotion"] is False
    assert context["summary"]["slices"] == 2
    assert context["summary"]["feature_rows"] == 3
    assert context["summary"]["schemas"] == {"mbo": 1, "mbp10": 1}

    nq = next(row for row in context["slices"] if row["root"] == "NQ")
    assert nq["rows"] == 2
    assert nq["metrics"]["events"]["sum"] == 300.0
    assert nq["metrics"]["spread_mean"]["mean"] == 0.375
    assert nq["metrics"]["book_depth_imbalance"]["mean"] == 0.05
    assert nq["feature_sha256"]
    assert nq["feature_path"].endswith("secondary/mbo/nq/2026-10-01.csv.gz")
    assert "raw_rows" not in nq
