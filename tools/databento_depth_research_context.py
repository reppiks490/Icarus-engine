"""Build a safe research-context projection from derived Databento depth features.

Only compact one-minute features are consumed. Raw licensed DBN/order-book rows
are neither read from the repository nor emitted by this artifact. The result is
research context only and never grants execution or production authority.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

OUTPUT = Path("automation_intelligence/cl_lab/databento_depth_research_context.json")
MANIFESTS = {
    "index": Path("automation_intelligence/cl_lab/databento_depth_corpus_index.json"),
    "diversifier": Path("automation_intelligence/cl_lab/databento_depth_corpus_diversifier.json"),
}
METRICS = (
    "events", "add_events", "cancel_events", "modify_events", "trade_events", "fill_events",
    "event_size", "add_size", "cancel_size", "trade_size", "bid_size", "ask_size",
    "bid_events", "ask_events", "latency_mean_ns", "latency_max_ns", "price_min", "price_max",
    "spread_mean", "depth10_bid_mean", "depth10_ask_mean", "event_size_imbalance",
    "cancel_add_size_ratio", "book_depth_imbalance",
)
ADDITIVE = {
    "events", "add_events", "cancel_events", "modify_events", "trade_events", "fill_events",
    "event_size", "add_size", "cancel_size", "trade_size", "bid_size", "ask_size",
    "bid_events", "ask_events",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _number(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _summarize(values: list[float], additive: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"samples": len(values)}
    if not values:
        return out
    total = sum(values)
    out.update(min=min(values), max=max(values), mean=total / len(values))
    if additive:
        out["sum"] = total
    return out


def summarize_slice(path: Path, depth_root: Path) -> dict[str, Any]:
    rel = path.relative_to(depth_root)
    parts = rel.parts
    if len(parts) != 5 or parts[0] != "features":
        raise ValueError(f"unexpected depth feature path: {rel}")
    _, account, schema, root, filename = parts
    day = filename.removesuffix(".csv.gz")
    values = {name: [] for name in METRICS}
    rows = 0
    first_ts = None
    last_ts = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            rows += 1
            ts = row.get("ts_minute") or row.get("timestamp")
            if ts:
                first_ts = ts if first_ts is None or ts < first_ts else first_ts
                last_ts = ts if last_ts is None or ts > last_ts else last_ts
            for name in METRICS:
                if name == "book_depth_imbalance":
                    continue
                value = _number(row.get(name))
                if value is not None:
                    values[name].append(value)
            bid = _number(row.get("depth10_bid_mean"))
            ask = _number(row.get("depth10_ask_mean"))
            if bid is not None and ask is not None and bid + ask:
                values["book_depth_imbalance"].append((bid - ask) / (bid + ask))
    return {
        "account": account,
        "schema": schema,
        "root": root.upper(),
        "day": day,
        "rows": rows,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "feature_path": rel.as_posix(),
        "feature_sha256": _sha256(path),
        "metrics": {
            name: _summarize(vals, name in ADDITIVE)
            for name, vals in values.items()
            if vals
        },
    }


def _manifest_summary(repo_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for lane, rel in MANIFESTS.items():
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result[lane] = {"status": "INVALID_MANIFEST"}
            continue
        requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
        statuses = Counter(str(row.get("status", "UNKNOWN")) for row in requests if isinstance(row, dict))
        result[lane] = {
            key: payload.get(key)
            for key in (
                "status", "profile", "account", "budget_usd", "max_request_usd",
                "estimated_requested_usd", "downloaded_slices", "cached_slices",
                "raw_retention", "feature_resolution", "selection_method",
            )
            if key in payload
        }
        result[lane]["request_statuses"] = dict(sorted(statuses.items()))
    return result


def build_context(repo_root: Path, depth_root: Path) -> dict[str, Any]:
    feature_root = depth_root / "features"
    slices = []
    if feature_root.is_dir():
        for path in sorted(feature_root.glob("*/*/*/*.csv.gz")):
            slices.append(summarize_slice(path, depth_root))
    schemas = Counter(row["schema"] for row in slices)
    accounts = Counter(row["account"] for row in slices)
    roots = Counter(row["root"] for row in slices)
    timestamps = [row["last_ts"] for row in slices if row.get("last_ts")]
    return {
        "schema_version": "icarus-databento-depth-research-context-v1",
        "authority": "RESEARCH_CONTEXT_ONLY",
        "status": "READY" if slices else "NO_FEATURE_SLICES",
        "snapshot_at_utc": max(timestamps) if timestamps else None,
        "source_feature_cache": str(depth_root),
        "source_feature_cache_committed": False,
        "raw_payloads_included": False,
        "raw_dbn_retained": False,
        "derived_feature_resolution": "1 minute",
        "descriptive_only": True,
        "candidate_evidence_eligible": False,
        "execution_authorized": False,
        "production_decision_authorized": False,
        "automatic_model_promotion": False,
        "summary": {
            "slices": len(slices),
            "feature_rows": sum(row["rows"] for row in slices),
            "schemas": dict(sorted(schemas.items())),
            "accounts": dict(sorted(accounts.items())),
            "roots": dict(sorted(roots.items())),
        },
        "manifests": _manifest_summary(repo_root),
        "slices": slices,
    }


def write_context(repo_root: Path, depth_root: Path, output: Path | None = None) -> Path:
    target = output or (repo_root / OUTPUT)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_context(repo_root, depth_root)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--depth-cache", type=Path, default=Path(".databento_depth_cache"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(write_context(args.repo_root, args.depth_cache, args.output))


if __name__ == "__main__":
    main()
