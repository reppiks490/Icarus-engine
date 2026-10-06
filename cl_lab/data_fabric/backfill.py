from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable, Mapping

from .acquisition import AcquisitionBudget, collect_json_pages, download_binary_dates
from cl_lab.providers import intrinio, unusual_whales


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
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("now must include timezone")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(obj, sort_keys=True, indent=2, default=str) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _redact(text: Any, secret: str) -> str:
    out = str(text)
    return out.replace(secret, "[REDACTED]") if secret else out


def _load_entitlement(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "manifests" / "latest.json"
    if not path.exists():
        return {"providers": {}}
    return json.loads(path.read_text())


def _dataset_name(provider: str, row: Mapping[str, Any]) -> str:
    if provider == "intrinio":
        return str(row.get("operation") or row.get("endpoint") or "unknown").strip("/").replace("/", "_").replace("{", "").replace("}", "")
    return str(row.get("name") or row.get("endpoint") or "unknown").strip("/").replace("/", "_")


def run_backfill_cycle(
    *,
    providers: Iterable[str] = ("intrinio", "unusual_whales"),
    env: Mapping[str, str] | None = None,
    entitlement: Mapping[str, Any] | None = None,
    output_dir: str | Path = ".external_data_cache",
    max_calls: int = 200,
    historical_floor: str = "2024-01-01",
    include_uw_full_tape: bool = False,
    collector: Callable[..., dict[str, Any]] = collect_json_pages,
    binary_downloader: Callable[..., dict[str, Any]] = download_binary_dates,
    now: Any = None,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    root = Path(output_dir)
    entitlement = dict(entitlement or _load_entitlement(root))
    retrieval_time = _now_iso(now)
    budget = AcquisitionBudget(int(max_calls))
    manifest: dict[str, Any] = {
        "schema": "icarus.external_data_fabric.backfill/1",
        "generated_at": retrieval_time,
        "historical_floor": historical_floor,
        "authority": "RESEARCH",
        "execution_authorized": False,
        "providers": {},
        "budget": {"max_calls": int(max_calls), "calls": 0},
    }
    uw_families = {e.name: e for e in unusual_whales.ENDPOINTS}

    for provider in providers:
        provider = str(provider)
        secret_env = SECRET_ENV.get(provider)
        if not secret_env:
            manifest["providers"][provider] = {"status": "error", "error_class": "unknown_provider", "datasets": {}}
            continue
        secret = str(env.get(secret_env, "") or "").strip()
        if not secret:
            manifest["providers"][provider] = {"status": "unconfigured", "credential_env": secret_env, "datasets": {}}
            continue

        prior = ((entitlement.get("providers") or {}).get(provider) or {})
        rows = list(prior.get("rows") or [])
        p_out: dict[str, Any] = {"status": "ok", "datasets": {}, "accessible_from_probe": sum(1 for r in rows if r.get("access") == "ACCESSIBLE")}

        for row in rows:
            if not budget.can_call():
                p_out["status"] = "partial_budget_exhausted"
                break
            if row.get("access") != "ACCESSIBLE":
                continue
            dataset = _dataset_name(provider, row)
            try:
                if provider == "intrinio":
                    endpoint = str(row.get("endpoint") or "")
                    resolved = str(row.get("resolved_path") or "")
                    target = intrinio.resolve_probe_target(endpoint)
                    if not resolved:
                        if getattr(target, "unresolved", ()):
                            p_out["datasets"][dataset] = {"status": "skipped_unresolved"}
                            continue
                        resolved = target.path
                    result = collector(
                        provider=provider,
                        dataset=dataset,
                        endpoint=endpoint,
                        url=intrinio.BASE_URL + resolved,
                        headers={"Authorization": f"Bearer {secret}"},
                        params=dict(getattr(target, "params", {}) or {}),
                        pagination="next_page",
                        output_root=root,
                        budget=budget,
                        retrieval_time=retrieval_time,
                        license_class="provider-restricted",
                        checkpoint_path=root / "checkpoints" / provider / f"{dataset}.json",
                        secrets=[secret],
                    )
                else:
                    family = uw_families.get(str(row.get("name") or ""))
                    if family is None:
                        p_out["datasets"][dataset] = {"status": "catalog_mismatch"}
                        continue
                    if family.pagination == "download":
                        # Large binary history is an explicit lane below.
                        continue
                    resolved = str(row.get("resolved_path") or "")
                    if not resolved:
                        target = unusual_whales.resolve_path(family.path)
                        if target.unresolved:
                            p_out["datasets"][dataset] = {"status": "skipped_unresolved"}
                            continue
                        resolved = target.path
                    paging = family.pagination if family.pagination in ("page", "offset") else "none"
                    params = dict(family.params or {})
                    # Backfill pages should not stay at the entitlement probe's one-row limit.
                    if "limit" in params:
                        params["limit"] = max(50, int(params["limit"]))
                    result = collector(
                        provider=provider,
                        dataset=dataset,
                        endpoint=family.path,
                        url=unusual_whales.BASE_URL + resolved,
                        headers={"Authorization": f"Bearer {secret}"},
                        params=params,
                        pagination=paging,
                        output_root=root,
                        budget=budget,
                        retrieval_time=retrieval_time,
                        license_class="provider-restricted",
                        checkpoint_path=root / "checkpoints" / provider / f"{dataset}.json",
                        secrets=[secret],
                    )
                p_out["datasets"][dataset] = {"status": "ok", **dict(result)}
            except Exception as exc:
                p_out["status"] = "partial"
                p_out["datasets"][dataset] = {"status": "error", "error_class": type(exc).__name__, "error": _redact(exc, secret)[:300]}

        if provider == "unusual_whales" and include_uw_full_tape and budget.can_call():
            try:
                result = binary_downloader(
                    provider="unusual_whales",
                    dataset="option_full_tape",
                    url_template=unusual_whales.BASE_URL + "/api/option-trades/full-tape/{date}",
                    headers={"Authorization": f"Bearer {secret}"},
                    start_date=historical_floor,
                    end_date=retrieval_time[:10],
                    output_root=root,
                    budget=budget,
                    retrieval_time=retrieval_time,
                    secrets=[secret],
                )
                p_out["datasets"]["option_full_tape"] = {"status": "ok", **dict(result)}
            except Exception as exc:
                p_out["status"] = "partial"
                p_out["datasets"]["option_full_tape"] = {"status": "error", "error_class": type(exc).__name__, "error": _redact(exc, secret)[:300]}

        manifest["providers"][provider] = p_out

    manifest["budget"]["calls"] = budget.calls
    manifest["budget"]["remaining"] = max(0, budget.max_calls - budget.calls)
    _atomic_json(root / "manifests" / "backfill_latest.json", manifest)
    return manifest
