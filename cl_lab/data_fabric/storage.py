from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

from .contracts import raw_sha256


def _utc(value: Any) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt.astimezone(timezone.utc)


def partition_for(value: Any) -> str:
    return f"date={_utc(value).date().isoformat()}"


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_bronze(root: str | Path, provider: str, dataset: str, payload: bytes, event_time: Any) -> dict[str, Any]:
    digest = raw_sha256(payload)
    path = Path(root) / "bronze" / provider / dataset / partition_for(event_time) / f"{digest}.bin.gz"
    compressed = gzip.compress(payload, compresslevel=6, mtime=0)
    if not path.exists():
        _atomic_bytes(path, compressed)
    return {"path": str(path), "sha256": digest, "bytes": len(payload), "compressed_bytes": path.stat().st_size}


def write_manifest(path: str | Path, obj: Any) -> dict[str, Any]:
    path = Path(path)
    data = (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    _atomic_bytes(path, data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str) for r in rows]
    return (("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))


def write_silver(root: str | Path, provider: str, dataset: str, rows: list[dict[str, Any]], event_time: Any) -> dict[str, Any]:
    base = Path(root) / "silver" / provider / dataset / partition_for(event_time)
    base.mkdir(parents=True, exist_ok=True)
    force_jsonl = os.environ.get("ICARUS_DATA_FABRIC_FORCE_JSONL") == "1"
    if not force_jsonl:
        try:
            import pyarrow as pa  # type: ignore
            import pyarrow.parquet as pq  # type: ignore
            table = pa.Table.from_pylist(rows)
            raw = _jsonl_bytes(rows)
            digest = hashlib.sha256(raw).hexdigest()
            path = base / f"part-{digest[:16]}.parquet"
            tmp = path.with_suffix(".parquet.tmp")
            pq.write_table(table, tmp, compression="zstd")
            os.replace(tmp, path)
            return {"path": str(path), "format": "parquet", "rows": len(rows), "sha256": digest, "bytes": path.stat().st_size}
        except ImportError:
            pass
    raw = _jsonl_bytes(rows)
    digest = hashlib.sha256(raw).hexdigest()
    path = base / f"part-{digest[:16]}.jsonl.gz"
    _atomic_bytes(path, gzip.compress(raw, compresslevel=6, mtime=0))
    return {"path": str(path), "format": "jsonl.gz", "rows": len(rows), "sha256": digest, "bytes": path.stat().st_size}
