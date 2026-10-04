# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.feeds CLI: refresh the cache and write the feed manifest
"""python -m cl_lab.feeds --cache .cl_cache --manifest automation_intelligence/cl_lab/feeds_manifest.json"""
from __future__ import annotations

import argparse
import json
import os

from .registry import refresh_all


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=".cl_cache")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    man = refresh_all(a.cache, only=set(filter(None, a.only.split(","))) or None)
    os.makedirs(os.path.dirname(os.path.abspath(a.manifest)), exist_ok=True)
    with open(a.manifest, "w") as f:
        json.dump(man, f, indent=1, sort_keys=True)
    for name, e in man["feeds"].items():
        rows = e.get("integrity", {}).get("rows", 0)
        print(f"{name:18s} {e['status']:5s} rows={rows} {e.get('error') or ''}"[:200])


if __name__ == "__main__":
    main()
