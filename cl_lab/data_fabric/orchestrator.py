from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable, Mapping

from cl_lab.providers import intrinio, unusual_whales


class CatalogIntegrityError(RuntimeError):
    pass


SECRET_ENV = {
    "intrinio": "INTRINIO_API_KEY",
    "unusual_whales": "UNUSUAL_WHALES_API_TOKEN",
}


def _now_iso(value: Any = None) -> str:
    if value is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("now must include timezone")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fetch_bytes(url: str) -> bytes:
    import urllib.request
    request = urllib.request.Request(url, headers={"User-Agent": "icarus-external-data-catalog/1", "Accept": "text/plain"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _redact(text: Any, secret: str | None) -> str:
    out = str(text)
    if secret:
        out = out.replace(str(secret), "[REDACTED]")
    return out


def summarize_access(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    materialized = list(rows)
    counts = Counter(str(row.get("access") or "MISSING_ACCESS") for row in materialized)
    ordered = {key: int(counts[key]) for key in sorted(counts)}
    total = len(materialized)
    accounted = sum(ordered.values())
    return {"total": total, "accounted": accounted, "counts": ordered, "integrity": total == accounted and total > 0}


def load_intrinio_catalog(
    *,
    fetch_bytes: Callable[[str], bytes] = _fetch_bytes,
    parser: Callable[[str], tuple[dict[str, Any], list[Any]]] = intrinio.parse_sdk_catalog,
    min_endpoints: int = 50,
) -> tuple[dict[str, Any], list[Any]]:
    raw = fetch_bytes(intrinio.SDK_README_URL)
    text = raw.decode("utf-8", "strict")
    meta, specs = parser(text)
    if len(specs) < int(min_endpoints):
        raise CatalogIntegrityError(f"Intrinio SDK catalog suspiciously small: {len(specs)} < {min_endpoints}")
    out = dict(meta)
    out.update(
        source=intrinio.SDK_README_URL,
        catalog_sha256=hashlib.sha256(raw).hexdigest(),
        endpoint_count=len(specs),
    )
    return out, specs


def _intrinio_probe_runner(secret: str) -> dict[str, Any]:
    meta, specs = load_intrinio_catalog()
    rows = intrinio.probe_catalog(specs, secret)
    return {
        "status": "ok",
        "catalog": {
            "source": meta.get("source"),
            "sha256": meta.get("catalog_sha256"),
            "api_version": meta.get("api_version"),
            "package_version": meta.get("package_version"),
            "endpoint_count": len(specs),
        },
        "rows": rows,
    }


def _uw_catalog_hash() -> str:
    payload = [
        {
            "name": e.name,
            "method": e.method,
            "path": e.path,
            "pagination": e.pagination,
            "stream_channel": e.stream_channel,
            "license_hint": e.license_hint,
        }
        for e in unusual_whales.ENDPOINTS
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _uw_probe_runner(secret: str) -> dict[str, Any]:
    rows = unusual_whales.probe_catalog(unusual_whales.ENDPOINTS, secret)
    return {
        "status": "ok",
        "catalog": {
            "source": "Unusual Whales published Public API documentation",
            "sha256": _uw_catalog_hash(),
            "endpoint_count": len(unusual_whales.ENDPOINTS),
        },
        "rows": rows,
    }


def build_gold_packet(manifest: Mapping[str, Any]) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for name, raw in (manifest.get("providers") or {}).items():
        entry = raw if isinstance(raw, Mapping) else {}
        providers[str(name)] = {
            "status": entry.get("status"),
            "catalog": dict(entry.get("catalog") or {}),
            "coverage": dict(entry.get("coverage") or {}),
        }
        if entry.get("error"):
            providers[str(name)]["error_class"] = entry.get("error_class") or "provider_error"
    return {
        "schema": "icarus.external_data_fabric.gold/1",
        "generated_at": manifest.get("generated_at"),
        "authority": "RESEARCH",
        "execution_authorized": False,
        "providers": providers,
    }


def run_probe_cycle(
    *,
    providers: Iterable[str] = ("intrinio", "unusual_whales"),
    env: Mapping[str, str] | None = None,
    output_dir: str | Path = ".external_data_cache",
    runners: Mapping[str, Callable[[str], dict[str, Any]]] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    runners = dict(runners or {})
    defaults = {"intrinio": _intrinio_probe_runner, "unusual_whales": _uw_probe_runner}
    generated_at = _now_iso(now)
    manifest: dict[str, Any] = {
        "schema": "icarus.external_data_fabric.entitlements/1",
        "generated_at": generated_at,
        "authority": "RESEARCH",
        "execution_authorized": False,
        "providers": {},
    }

    for provider in providers:
        provider = str(provider)
        if provider not in SECRET_ENV:
            manifest["providers"][provider] = {"status": "error", "error_class": "unknown_provider"}
            continue
        secret = str(env.get(SECRET_ENV[provider], "") or "").strip()
        if not secret:
            manifest["providers"][provider] = {
                "status": "unconfigured",
                "credential_env": SECRET_ENV[provider],
                "coverage": {"total": 0, "accounted": 0, "counts": {}, "integrity": True},
            }
            continue
        runner = runners.get(provider) or defaults[provider]
        try:
            result = dict(runner(secret))
            rows = list(result.get("rows") or [])
            result["coverage"] = summarize_access(rows)
            manifest["providers"][provider] = result
        except Exception as exc:
            manifest["providers"][provider] = {
                "status": "error",
                "error_class": type(exc).__name__,
                "error": _redact(exc, secret)[:300],
                "coverage": {"total": 0, "accounted": 0, "counts": {}, "integrity": False},
            }

    root = Path(output_dir)
    _write_json_atomic(root / "manifests" / "latest.json", manifest)
    gold = build_gold_packet(manifest)
    _write_json_atomic(root / "gold" / "latest.json", gold)
    return manifest
