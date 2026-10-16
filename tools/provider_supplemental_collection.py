"""Additive collection bridge for credentialed providers missing from K1.

This module deliberately reuses the existing provider collection state, encrypted
archive, receipts, MCP events and research-context aggregation.  It does not
replace the Claude-owned K1 collector.  It extends it at runtime for the
supplemental official endpoint catalog only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from tools import provider_exhaustive_collection as core


EXTENDED_PROVIDERS = {
    "unusual_whales": {
        "base": "https://api.unusualwhales.com",
        "keys": ["UNUSUAL_WHALES_API_KEY"],
        "auth": "bearer",
    },
    "alphavantage": {
        "base": "https://www.alphavantage.co",
        "keys": ["ALPHAVANTAGE_API_KEY"],
        "auth": "alphavantage",
    },
    "finnhub": {
        "base": "https://finnhub.io/api/v1",
        "keys": ["FINNHUB_API_KEY"],
        "auth": "finnhub",
    },
}

CATALOG_PATHS = {
    "/api/screener/stocks",
    "/api/crypto/list_tokens",
    "/stock/symbol",
}

_ORIGINAL = {
    "rows": core.rows,
    "bind": core.bind,
    "seed": core.seed,
    "next_page": core.next_page,
    "check_response": core.check_response,
}


def _date_example(value: object) -> object:
    if not isinstance(value, str) or not value.startswith("__"):
        return value
    today = datetime.now(timezone.utc).date()
    mapping = {
        "__TODAY__": today,
        "__7D_AGO__": today - timedelta(days=7),
        "__30D_AGO__": today - timedelta(days=30),
        "__30D_AHEAD__": today + timedelta(days=30),
    }
    return mapping.get(value, value).isoformat() if value in mapping else value


def rows(data):
    found = _ORIGINAL["rows"](data)
    if found:
        return found
    if not isinstance(data, dict):
        return []

    nested = data.get("data")
    if isinstance(nested, dict):
        found = rows(nested)
        if found:
            return found

    for name in (
        "bestMatches",
        "top_gainers",
        "top_losers",
        "most_actively_traded",
        "feed",
        "earningsCalendar",
        "economicCalendar",
    ):
        if isinstance(data.get(name), list):
            return [row for row in data[name] if isinstance(row, dict)]

    quote = data.get("Global Quote")
    if isinstance(quote, dict) and quote:
        return [quote]

    for name, value in data.items():
        if "time series" in name.lower() and isinstance(value, dict):
            out = []
            for stamp, raw in value.items():
                if not isinstance(raw, dict):
                    continue
                normalized = {"timestamp": stamp}
                for key, item in raw.items():
                    clean = re.sub(r"^\d+\.\s*", "", str(key)).strip().lower().replace(" ", "_")
                    normalized[clean] = item
                out.append(normalized)
            return out
    return []


def bind(op, asset=None):
    prepared = {**op, "parameters": []}
    for parameter in op.get("parameters", []):
        prepared["parameters"].append({**parameter, "example": _date_example(parameter.get("example"))})
    path, params, unresolved = _ORIGINAL["bind"](prepared, asset)

    # The legacy binder uses one generic interval default.  For official
    # supplemental operations preserve the provider-specific documented example.
    for parameter in prepared.get("parameters", []):
        name = parameter["name"]
        value = parameter.get("example")
        if (
            parameter.get("location") == "query"
            and value is not None
            and not core.SECRET.search(name)
            and not isinstance(value, (dict, list))
        ):
            params.setdefault(name, value)
            if name == "interval":
                params[name] = value
    return path, params, unresolved


def seed(db, operations):
    for op in operations:
        provider = op.get("provider") or op["id"].split(":", 1)[0]
        if provider not in core.PROVIDERS:
            raise ValueError("provider is not admitted")
        op = {**op, "provider": provider}
        asset_parameters = [
            p for p in op.get("parameters", []) if p["name"].lower() in core.ASSET_NAMES
        ]
        unresolved_asset = any(p.get("example") is None for p in asset_parameters)
        asset_mode = bool(asset_parameters) and unresolved_asset and (
            op["path"] not in core.CATALOG_PATHS
            or any(p.get("required") and p.get("example") is None for p in asset_parameters)
        )
        path, params, missing = bind(op)
        status = (
            "NON_READ_OPERATION"
            if op["method"] != "GET"
            else "ASSET_TEMPLATE"
            if asset_mode
            else "PARAMETER_BINDING_BLOCKED"
            if missing
            else "QUEUED"
        )
        db.execute(
            "INSERT INTO operations VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET descriptor=excluded.descriptor,status=excluded.status",
            (op["id"], provider, json.dumps(op), status),
        )
        if status == "QUEUED":
            db.execute(
                "INSERT OR IGNORE INTO jobs(operation,path,params,status) VALUES(?,?,?,?)",
                (op["id"], path, json.dumps(params), "PENDING"),
            )
    db.commit()


def next_page(provider, data, current):
    if isinstance(data, dict) and data.get("next_token"):
        return {"params": {**current, "next_token": data["next_token"]}}
    continuation = _ORIGINAL["next_page"](provider, data, current)
    if continuation:
        return continuation
    if provider == "unusual_whales" and current.get("limit"):
        count = len(rows(data))
        limit = int(current["limit"])
        if count >= limit:
            if "page" in current:
                return {"params": {**current, "page": int(current["page"]) + 1}}
            if "offset" in current:
                return {"params": {**current, "offset": int(current["offset"]) + 1}}
    return None


def check_response(data):
    _ORIGINAL["check_response"](data)
    if not isinstance(data, dict):
        return
    note = str(data.get("Note") or "")
    info = str(data.get("Information") or "")
    message = " ".join((note, info)).strip()
    if not message:
        return
    if re.search(r"rate|frequency|call limit|higher API call", message, re.I):
        raise core.ProviderFailure("429")
    if re.search(r"premium|subscription|entitlement|upgrade", message, re.I):
        raise core.ProviderFailure("403")


def request(provider, path, params, key):
    spec = core.PROVIDERS[provider]
    if not path.startswith("/") or "://" in path or ".." in path or core.SECRET.search(path):
        raise ValueError("unsafe path")
    safe = {k: v for k, v in params.items() if v is not None and not core.SECRET.search(k)}
    headers = {"User-Agent": "ICARUS-catalog-acquisition/1", "Accept": "application/json"}
    if provider == "unusual_whales":
        headers["Authorization"] = "Bearer " + key
    elif provider == "alphavantage":
        safe["apikey"] = key
    elif provider == "finnhub":
        safe["token"] = key
    else:
        return core.request(provider, path, safe, key)

    url = spec["base"] + path + ("?" + urlencode(safe, doseq=True) if safe else "")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise core.ProviderFailure("REDIRECT_BLOCKED")

    with urllib.request.build_opener(NoRedirect).open(
        urllib.request.Request(url, headers=headers), timeout=20
    ) as response:
        raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise core.ProviderFailure("PAYLOAD_LIMIT_INCOMPLETE")
    return json.loads(raw)


def install_extensions() -> None:
    core.PROVIDERS.update(EXTENDED_PROVIDERS)
    core.CATALOG_PATHS.update(CATALOG_PATHS)
    core.rows = rows
    core.bind = bind
    core.seed = seed
    core.next_page = next_page
    core.check_response = check_response


def load_operations(root: Path, provider: str) -> list[dict]:
    data = json.loads((root / "config/provider_endpoint_catalog_supplemental.json").read_text())
    return [op for op in data["operations"] if op["provider"] == provider]


def run_cycle(
    root: Path,
    provider: str,
    env: dict[str, str],
    *,
    run_id: str,
    request_budget: int = 20,
    delay_seconds: float = 13,
):
    install_extensions()
    return core.cycle(
        root,
        load_operations(root, provider),
        env,
        run_id=run_id,
        request_budget=request_budget,
        fetch=request,
        delay_seconds=delay_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--request-budget", type=int, default=20)
    parser.add_argument("--delay-seconds", type=float, default=13)
    parser.add_argument("--provider", required=True, choices=sorted(EXTENDED_PROVIDERS))
    args = parser.parse_args()
    result = run_cycle(
        args.root,
        args.provider,
        dict(os.environ),
        run_id=args.run_id,
        request_budget=args.request_budget,
        delay_seconds=args.delay_seconds,
    )
    print(
        json.dumps(
            {
                "providers": {k: v["status"] for k, v in result["providers"].items()},
                "requests": result["requests"],
                "coverage": result["catalog"],
            }
        )
    )


if __name__ == "__main__":
    main()
