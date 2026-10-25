"""Validate an untrusted corpus-consumer receipt and publish metadata only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat


WORKSPACES = frozenset(("cc1", "cc2", "cc3", "cc4"))
CACHES = frozenset(("bars_primary", "bars_secondary", "bars_third"))
PURPOSES = frozenset(("QUALITY_AND_COVERAGE", "PRIVATE_HISTORY_INPUT", "PAPER_CONFIGURATION_WARMUP"))
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SYMBOL = re.compile(r"[A-Z0-9]{1,16}\Z")
ROOT = re.compile(r"[A-Za-z0-9]{1,16}\Z")
TOKEN = re.compile(r"[A-Z0-9_]{1,64}\Z")
FILENAME = re.compile(r"databento_(?:hist_)?[a-z0-9]+_5m\.csv\.gz\Z")


def _integer(value, *, minimum=0, maximum=2_000_000_000_000_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid corpus receipt integer")
    return value


def _string(value, pattern, *, maximum=128):
    if type(value) is not str or len(value) > maximum or not pattern.fullmatch(value):
        raise ValueError("invalid corpus receipt token")
    return value


def _boolean(value):
    if type(value) is not bool:
        raise ValueError("invalid corpus receipt flag")
    return value


def _hash(value):
    return _string(value, SHA256, maximum=64)


def _read_private_json(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > 8 * 1024 * 1024:
            raise ValueError("invalid corpus receipt file")
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("corpus receipt exceeds size limit")
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate corpus receipt field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique_object)


def _dataset(row, engine_sha):
    if type(row) is not dict or row.get("source_repo") != "reppiks490/Icarus-engine":
        raise ValueError("unrecognized corpus dataset")
    if row.get("source_commit") != engine_sha or row.get("provider") != "databento":
        raise ValueError("corpus dataset provenance mismatch")
    filename = row.get("filename")
    if type(filename) is not str or not FILENAME.fullmatch(filename):
        raise ValueError("invalid corpus filename")
    cache = row.get("cache_name")
    if cache not in CACHES:
        raise ValueError("invalid corpus cache")
    return {
        "dataset_id": _hash(row.get("dataset_id")),
        "provider": "databento",
        "symbol": _string(row.get("symbol"), SYMBOL, maximum=16),
        "provider_root": _string(row.get("provider_root"), ROOT, maximum=16),
        "identity_status": _string(row.get("identity_status"), TOKEN),
        "source_commit": engine_sha,
        "source_sha256": _hash(row.get("source_sha256")),
        "bars_sha256": _hash(row.get("bars_sha256")),
        "manifest_sha256": _hash(row.get("manifest_sha256")),
        "cache_name": cache,
        "filename": filename,
        "retained_rows": _integer(row.get("retained_rows"), minimum=1, maximum=200_000),
        "first_ts": _integer(row.get("first_ts")),
        "last_ts": _integer(row.get("last_ts")),
        "available_at_ns": _integer(row.get("available_at_ns")),
        "asof_ns": _integer(row.get("asof_ns")),
        "native_interval_seconds": _integer(row.get("native_interval_seconds"), minimum=1, maximum=86400),
        "entitlement_status": "UNVERIFIED",
        "live_feed_qualified": False,
        "strategy_qualified": False,
        "execution_authorized": False,
    }


def _read_receipt(row, engine_sha, dataset_ids):
    if type(row) is not dict or row.get("source_repo") != "reppiks490/Icarus-engine":
        raise ValueError("unrecognized corpus read receipt")
    if row.get("source_commit") != engine_sha:
        raise ValueError("corpus read provenance mismatch")
    dataset_id = _hash(row.get("dataset_id"))
    if dataset_id not in dataset_ids:
        raise ValueError("read receipt has no admitted dataset")
    consumer = row.get("consumer_id")
    if consumer not in {"history_intake", *("paper:" + item for item in WORKSPACES)}:
        raise ValueError("invalid corpus reader identity")
    method = _string(row.get("method"), re.compile(r"(?:ticker|daily_volume|candles|recent_ex|recent)\Z"), maximum=32)
    first_ts, last_ts = row.get("first_ts"), row.get("last_ts")
    if first_ts is not None:
        first_ts = _integer(first_ts)
    if last_ts is not None:
        last_ts = _integer(last_ts)
    if (first_ts is None) != (last_ts is None) or first_ts is not None and last_ts < first_ts:
        raise ValueError("invalid corpus read interval")
    return {
        "consumer_id": consumer,
        "method": method,
        "dataset_id": dataset_id,
        "symbol": _string(row.get("symbol"), SYMBOL, maximum=16),
        "requested_interval_seconds": _integer(row.get("requested_interval_seconds"), minimum=1, maximum=86400),
        "row_count": _integer(row.get("row_count"), maximum=2_000_000),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "available_at_ns": _integer(row.get("available_at_ns")),
        "asof_ns": _integer(row.get("asof_ns")),
        "entitlement_status": "UNVERIFIED",
        "live_feed_qualified": False,
        "strategy_qualified": False,
        "execution_authorized": False,
    }


def _workspace(row, dataset_ids):
    if type(row) is not dict or row.get("id") not in WORKSPACES:
        raise ValueError("invalid corpus workspace")
    seen = set()
    assets = []
    raw_assets = row.get("assets")
    if type(raw_assets) is not list or len(raw_assets) > 128:
        raise ValueError("invalid corpus asset list")
    for asset in raw_assets:
        if type(asset) is not dict:
            raise ValueError("invalid warmed asset")
        if asset.get("mode") != "CORPUS_WARMUP" or asset.get("execution_authorized") is not False:
            raise ValueError("invalid corpus runtime mode")
        dataset_id = _hash(asset.get("dataset_id"))
        symbol = _string(asset.get("symbol"), SYMBOL, maximum=16)
        if dataset_id not in dataset_ids or symbol in seen:
            raise ValueError("warmed asset lacks a unique dataset")
        seen.add(symbol)
        warm = _boolean(asset.get("warm"))
        bars = _integer(asset.get("chart_bars"), maximum=200_000)
        assets.append({"symbol": symbol, "dataset_id": dataset_id,
                       "warm": warm, "chart_bars": bars,
                       "native_interval_seconds": _integer(asset.get("native_interval_seconds"), minimum=1, maximum=86400)})
    raw_unavailable = row.get("unavailable_assets", [])
    if type(raw_unavailable) is not list or len(raw_unavailable) > 128:
        raise ValueError("invalid unavailable asset list")
    unavailable = sorted({_string(item, SYMBOL, maximum=16) for item in raw_unavailable})
    paper_only, execution_authorized = _boolean(row.get("paper_only")), _boolean(row.get("execution_authorized"))
    if not paper_only or execution_authorized:
        raise ValueError("workspace exceeded paper-only authority")
    return {"id": row["id"], "configuration_sha256": _hash(row.get("configuration_sha256")),
            "assets": assets, "unavailable_asset_symbols": unavailable,
            "paper_only": paper_only, "execution_authorized": execution_authorized}


def sanitize_receipt(input_path: Path, output_path: Path, *, engine_sha: str, consumer_sha: str,
                     cache_name: str, available_at_ns: int, consumer_exit_code: int):
    _string(engine_sha, SHA1, maximum=40)
    _string(consumer_sha, SHA1, maximum=40)
    if (cache_name not in CACHES or type(consumer_exit_code) is not int
            or consumer_exit_code not in (0, 1)):
        raise ValueError("invalid corpus workflow provenance")
    available_at_ns = _integer(available_at_ns)
    doc = _read_private_json(Path(input_path))
    if type(doc) is not dict or doc.get("schema_version") != "icarus-corpus-consumption-v1":
        raise ValueError("unrecognized corpus consumption receipt")
    if (doc.get("source_repo") != "reppiks490/Icarus-engine"
            or doc.get("source_commit") != engine_sha
            or any(doc.get(key) is not False for key in
                   ("raw_payloads_included", "execution_authorized", "production_decision_authorized", "market_validation"))):
        raise ValueError("corpus receipt exceeded its authority")
    asof_ns = _integer(doc.get("asof_ns"))
    raw_datasets, raw_reads, raw_workspaces = doc.get("datasets"), doc.get("read_receipts"), doc.get("workspaces")
    if (type(raw_datasets) is not list or not raw_datasets or len(raw_datasets) > 200
            or type(raw_reads) is not list or len(raw_reads) > 4000
            or type(raw_workspaces) is not list or len(raw_workspaces) != 4):
        raise ValueError("incomplete corpus receipt")
    datasets = [_dataset(row, engine_sha) for row in raw_datasets]
    if any(row["available_at_ns"] != available_at_ns or row["asof_ns"] != asof_ns for row in datasets):
        raise ValueError("corpus dataset availability/as-of clock mismatch")
    dataset_ids = {row["dataset_id"] for row in datasets}
    if len(dataset_ids) != len(datasets) or any(row["cache_name"] != cache_name for row in datasets):
        raise ValueError("duplicate or foreign corpus dataset")
    reads = [_read_receipt(row, engine_sha, dataset_ids) for row in raw_reads]
    if any(row["available_at_ns"] != available_at_ns or row["asof_ns"] != asof_ns for row in reads):
        raise ValueError("corpus read availability/as-of clock mismatch")
    read_ids = {row["dataset_id"] for row in reads if row["row_count"] > 0}
    if not dataset_ids.issubset(read_ids):
        raise ValueError("not every retained dataset was read")
    workspaces = [_workspace(row, dataset_ids) for row in raw_workspaces]
    if {row["id"] for row in workspaces} != WORKSPACES:
        raise ValueError("the four selected workspaces were not observed")
    corpus_used = any(row["row_count"] > 0 for row in reads)
    if doc.get("corpus_used") is not corpus_used:
        raise ValueError("corpus use claim does not match read receipts")
    paper_warmup_used = any(asset["warm"] and asset["chart_bars"] > 0
                            for row in workspaces for asset in row["assets"])
    paper_warmup_status = "WARMED" if paper_warmup_used else "NOT_WARMED"
    if doc.get("paper_warmup_used") is not paper_warmup_used:
        raise ValueError("paper warmup claim does not match asset observations")
    purposes = doc.get("consumption_purposes")
    if type(purposes) is not list or len(set(purposes)) != len(purposes) or not set(purposes) <= PURPOSES:
        raise ValueError("invalid corpus purpose summary")
    blocked = doc.get("blocked_datasets", [])
    if type(blocked) is not list or len(blocked) > 200:
        raise ValueError("invalid blocked dataset summary")
    blocked_rows = []
    for row in blocked:
        if type(row) is not dict or row.get("reason") != "DATASET_VALIDATION_FAILED":
            raise ValueError("invalid blocked dataset row")
        blocked_rows.append({"input_sha256": _hash(row.get("input_sha256")),
                             "reason": "DATASET_VALIDATION_FAILED"})
    if (consumer_exit_code == 1) != bool(blocked_rows):
        raise ValueError("consumer exit status does not match partial dataset admission")
    consumer_status = "PARTIAL" if consumer_exit_code == 1 else "COMPLETE"
    safe = {
        "schema_version": "icarus-corpus-consumption-v1",
        "source_repo": "reppiks490/Icarus-engine", "source_commit": engine_sha,
        "consumer_repo": "reppiks490/Icarus", "consumer_commit": consumer_sha,
        "cache_name": cache_name, "asof_ns": asof_ns,
        "available_at_ns": available_at_ns, "datasets": datasets,
        "blocked_datasets": blocked_rows, "read_receipts": reads,
        "workspaces": workspaces, "corpus_used": corpus_used,
        "consumer_exit_code": consumer_exit_code, "consumer_status": consumer_status,
        "paper_warmup_used": paper_warmup_used, "paper_warmup_status": paper_warmup_status,
        "consumption_purposes": sorted(purposes),
        "raw_payloads_included": False, "execution_authorized": False,
        "production_decision_authorized": False, "market_validation": False,
        "workflow_provenance": {"engine_commit": engine_sha, "consumer_commit": consumer_sha,
                                "network_disabled": True, "acquisition_performed": False,
                                "consumer_exit_code": consumer_exit_code,
                                "consumer_status": consumer_status,
                                "paper_warmup_status": paper_warmup_status,
                                "raw_data_artifacted": False, "execution_authorized": False},
    }
    payload = (json.dumps(safe, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    parent = Path(output_path).parent
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = Path(output_path).with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output_path)
    os.chmod(output_path, 0o600)
    return safe


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine-sha", required=True)
    parser.add_argument("--consumer-sha", required=True)
    parser.add_argument("--cache-name", choices=sorted(CACHES), required=True)
    parser.add_argument("--available-at-ns", type=int, required=True)
    parser.add_argument("--consumer-exit-code", type=int, choices=(0, 1), required=True)
    args = parser.parse_args(argv)
    sanitize_receipt(args.input, args.output, engine_sha=args.engine_sha, consumer_sha=args.consumer_sha,
                     cache_name=args.cache_name, available_at_ns=args.available_at_ns,
                     consumer_exit_code=args.consumer_exit_code)


if __name__ == "__main__":
    main()
