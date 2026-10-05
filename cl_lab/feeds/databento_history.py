# CL (Claude, Anthropic) — 2026-10-04 — CL lane on the 4th Databento key: long-history NQ/ES backfill
"""Backfills continuous NQ and ES 1-minute OHLCV from June 2010 up to the start of the key #1
corpus (2024-09-01), so the lab can test every rule on ~14 years it has never seen.

Spending rules (estimates come from Databento's free ``metadata.get_cost``):
- one request = one calendar year of one root; a request above MAX_USD_PER_REQUEST is not sent;
- at most MAX_USD_PER_RUN per workflow run and MAX_USD_LIFETIME for the whole lane, enforced
  against a committed ledger (automation_intelligence/cl_lab/history_ledger.json) so a lost
  Actions cache can never trigger silent re-spending past the lifetime cap;
- chunks already in the ledger AND present in the cache are skipped (idempotent).
Raw rows live only in the Actions cache (``databento_hist_{root}_5m.csv.gz``); the repository
receives the ledger (ranges, row counts, estimates), never vendor rows."""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

import pandas as pd

from .. import store
from . import databento as dbf

ACCOUNT = "cl"
ROOTS = (("NQ", "GLBX.MDP3"), ("ES", "GLBX.MDP3"))
START = pd.Timestamp("2010-06-07T00:00:00Z")      # first full week of GLBX.MDP3 history
END = pd.Timestamp("2024-09-01T00:00:00Z")        # key #1's corpus begins here
MAX_USD_PER_REQUEST, MAX_USD_PER_RUN, MAX_USD_LIFETIME = 15.0, 15.0, 60.0
LEDGER_IN_CACHE = "databento_history_ledger.json"


def chunks():
    out, a = [], START
    while a < END:
        b = min(pd.Timestamp(f"{a.year + 1}-01-01T00:00:00Z"), END)
        out.append((a, b))
        a = b
    return out


def cache_path(cache_dir, root):
    return os.path.join(cache_dir, f"databento_hist_{root.lower()}_5m.csv.gz")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def run(cache_dir: str, ledger_path: str, *, client: Any = None, now=None) -> dict:
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    copies = [x for x in (_load(ledger_path), _load(os.path.join(cache_dir, LEDGER_IN_CACHE))) if x]
    # the committed ledger and the cached copy can diverge if a run dies before committing: keep the larger spend
    led = max(copies, key=lambda x: x.get("spent_estimated_usd", 0.0)) if copies else dict(schema="cl_lab.databento_history/1", lane="CL", account=ACCOUNT,
                                     key_env=dbf.api_key_env(ACCOUNT), caps=dict(per_request=MAX_USD_PER_REQUEST,
                                     per_run=MAX_USD_PER_RUN, lifetime=MAX_USD_LIFETIME), spent_estimated_usd=0.0, chunks={})
    led["last_run_at"], led["run_status"], run_spent, notes = now.isoformat(), "OK", 0.0, []
    if client is None and not dbf.account_configured(ACCOUNT):
        led["run_status"] = f"UNCONFIGURED: {dbf.api_key_env(ACCOUNT)} not set"
        return _save(led, ledger_path, (), cache_dir)
    client = client or dbf.historical_client(account=ACCOUNT)
    for root, dataset in ROOTS:
        path = cache_path(cache_dir, root)
        frame = store.load_frame(path) if os.path.exists(path) else pd.DataFrame()
        for a, b in chunks():
            key = f"{root}:{a.date()}..{b.date()}"
            have = not frame.empty and ((frame.index >= a) & (frame.index < b)).any()
            if have:                      # never pay twice for rows already cached
                if led["chunks"].get(key, {}).get("status") != "DONE":
                    led["chunks"][key] = dict(led["chunks"].get(key, {}), status="DONE", source="cache")
                continue
            kw = dict(dataset=dataset, symbols=dbf.continuous_symbol(root, "v"), schema="ohlcv-1m",
                      stype_in="continuous", start=a.isoformat(), end=b.isoformat())
            try:
                est = float(dbf._retry(lambda: client.metadata.get_cost(**kw)))
            except Exception as ex:  # noqa: BLE001 - recorded, never raised
                led["chunks"][key] = dict(status="ESTIMATE_FAILED", error=f"{type(ex).__name__}: {ex}"[:200])
                continue
            if est > MAX_USD_PER_REQUEST:
                led["chunks"][key] = dict(status="OVER_REQUEST_CAP", estimate_usd=round(est, 4))
                continue
            if run_spent + est > MAX_USD_PER_RUN or led["spent_estimated_usd"] + est > MAX_USD_LIFETIME:
                notes.append(f"budget reached before {key} (estimate ${est:.4f})")
                led["run_status"] = "BUDGET_PAUSED"
                return _save(led, ledger_path, notes, cache_dir)
            try:
                store_ = dbf._retry(lambda: client.timeseries.get_range(**kw))
                part = dbf.resample_5m(dbf._as_ohlcv_1m(store_))
            except Exception as ex:  # noqa: BLE001
                led["chunks"][key] = dict(status="REQUEST_FAILED", estimate_usd=round(est, 4), error=f"{type(ex).__name__}: {ex}"[:200])
                continue
            run_spent += est
            led["spent_estimated_usd"] = round(led["spent_estimated_usd"] + est, 6)
            frame = store.merge_frames(frame, part)
            store.save_frame(frame, path)
            led["chunks"][key] = dict(status="DONE", estimate_usd=round(est, 4), rows_5m=int(len(part)),
                                      first=part.index[0].isoformat() if len(part) else None,
                                      last=part.index[-1].isoformat() if len(part) else None, at=now.isoformat())
    return _save(led, ledger_path, notes, cache_dir)


def _save(led, ledger_path, notes=(), cache_dir=None):
    led["notes"] = list(notes)[:10]
    led["execution_authorized"] = False
    for path in [ledger_path] + ([os.path.join(cache_dir, LEDGER_IN_CACHE)] if cache_dir else []):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(led, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    return led


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=".cl_cache")
    ap.add_argument("--ledger", default="automation_intelligence/cl_lab/history_ledger.json")
    a = ap.parse_args(argv)
    led = run(a.cache, a.ledger)
    print(json.dumps({k: led.get(k) for k in ("run_status", "spent_estimated_usd", "notes")}))


if __name__ == "__main__":
    main()
