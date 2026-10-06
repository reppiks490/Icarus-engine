#!/usr/bin/env python3
"""CLI for the ICARUS external provider entitlement/backfill fabric.

Research-data authority only. Secrets are read from environment and are never
written to manifests or command-line arguments.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from cl_lab.data_fabric.backfill import run_backfill_cycle
from cl_lab.data_fabric.orchestrator import run_probe_cycle


def _providers(value: str) -> tuple[str, ...]:
    if value == "all":
        return ("intrinio", "unusual_whales")
    return (value,)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="ICARUS external provider data fabric")
    p.add_argument("mode", choices=("probe", "backfill", "incremental"))
    p.add_argument("--provider", choices=("all", "intrinio", "unusual_whales"), default="all")
    p.add_argument("--cache", default=".external_data_cache")
    p.add_argument("--max-calls", type=int, default=200)
    p.add_argument("--historical-floor", default="2024-01-01")
    p.add_argument("--include-uw-full-tape", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    providers = _providers(args.provider)
    root = Path(args.cache)

    if args.mode == "probe":
        manifest = run_probe_cycle(providers=providers, output_dir=root)
    else:
        entitlement_path = root / "manifests" / "latest.json"
        if not entitlement_path.exists():
            run_probe_cycle(providers=providers, output_dir=root)
        manifest = run_backfill_cycle(
            providers=providers,
            output_dir=root,
            max_calls=max(1, args.max_calls),
            historical_floor=args.historical_floor,
            include_uw_full_tape=bool(args.include_uw_full_tape and args.mode == "backfill"),
        )

    # Stdout is deliberately compact; full manifests stay in the cache/artifacts.
    summary = {
        "schema": manifest.get("schema"),
        "generated_at": manifest.get("generated_at"),
        "providers": {name: {"status": info.get("status")} for name, info in (manifest.get("providers") or {}).items()},
        "budget": manifest.get("budget"),
    }
    print(json.dumps(summary, sort_keys=True))

    # Missing subscription/credentials is not an integrity failure. A malformed
    # provider catalog is, because continuing could silently omit endpoints.
    if any(info.get("error_class") == "CatalogIntegrityError" for info in (manifest.get("providers") or {}).values()):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
