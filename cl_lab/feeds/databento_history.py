# CL (Claude, Anthropic) — 2026-10-04 (rev. 2026-10-05) — long-history NQ/ES backfill on the owner's budget split
"""Backfills continuous NQ and ES 1-minute OHLCV from June 2010 up to the start of the key #1 corpus
(2024-09-01), so the lab can test every rule on ~14 years it has never seen.

Owner decision 2026-10-05 (the 4th key's account is locked by Databento): the cost is split across
the remaining credit of keys #1-#3 (``databento_budget``): NQ on key #3 (lane ``history:NQ``), ES on
key #1 (lane ``history:ES``), each with a lifetime cap. Years are bought NEWEST FIRST; when a lane's
remaining cap cannot buy the next older year, that year is shortened from its old end to what fits,
and anything older is skipped. Only the length of history shrinks, never the schema or resolution.

Per-request and per-run limits (MAX_USD_PER_REQUEST, MAX_USD_PER_RUN) spread the work across runs;
estimates come from Databento's free ``metadata.get_cost``. A 401/403/auth error stops the lane at
once. Raw rows live only in the Actions cache (``databento_hist_{root}_5m.csv.gz``); the repository
receives the ledgers (ranges, row counts, estimates), never vendor rows."""
from __future__ import annotations

import argparse
import json
import os

import pandas as pd

from .. import store
from . import databento as dbf
from . import databento_budget as budget

ROOTS = (("NQ", "GLBX.MDP3", "history:NQ"), ("ES", "GLBX.MDP3", "history:ES"))
START = pd.Timestamp("2010-06-07T00:00:00Z")      # first full week of GLBX.MDP3 history
END = pd.Timestamp("2024-09-01T00:00:00Z")        # key #1's corpus begins here
MAX_USD_PER_REQUEST, MAX_USD_PER_RUN = 15.0, 15.0
AUTH_ERRORS = ("401", "403", "auth_")   # e.g. "403 auth_account_locked" observed 2026-10-05


def chunks():
    """Calendar-year windows, newest first."""
    out, a = [], START
    while a < END:
        b = min(pd.Timestamp(f"{a.year + 1}-01-01T00:00:00Z"), END)
        out.append((a, b))
        a = b
    return out[::-1]


def cache_path(cache_dir, root):
    return os.path.join(cache_dir, f"databento_hist_{root.lower()}_5m.csv.gz")


def _kw(root, dataset, a, b):
    return dict(dataset=dataset, symbols=dbf.continuous_symbol(root, "v"), schema="ohlcv-1m",
                stype_in="continuous", start=a.isoformat(), end=b.isoformat())


def run(cache_dir: str, ledger_dir: str = budget.LEDGER_DIR, *, clients: dict | None = None, now=None) -> dict:
    """``clients``: optional {account: client} (tests). Returns a status per root."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    budget.check_split()
    clients = dict(clients or {})
    out = {}
    run_spent = 0.0
    for root, dataset, lane_id in ROOTS:
        lane = budget.Lane(lane_id, ledger_dir, mirror=cache_dir)
        account = lane.cfg["account"]
        st = out[root] = dict(lane=lane_id, account=account, key_env=dbf.api_key_env(account), status="OK",
                              cap_usd=lane.cfg["cap_usd"], spent_usd=lane.data["spent_usd"], bought=[], trimmed=None)
        if account not in clients:
            if not dbf.account_configured(account):
                st["status"] = f"UNCONFIGURED: {dbf.api_key_env(account)} not set"
                continue
            clients[account] = dbf.historical_client(account=account)
        client = clients[account]
        path = cache_path(cache_dir, root)
        frame = store.load_frame(path) if os.path.exists(path) else pd.DataFrame()
        for a, b in chunks():
            if not frame.empty and ((frame.index >= a) & (frame.index < b)).any():
                continue                                   # cached: never pay twice
            if lane.data.get("exhausted_before"):          # an older year was already cut: nothing older to buy
                st["status"] = "CAP_REACHED"
                break
            kw = _kw(root, dataset, a, b)
            try:
                est = float(dbf._retry(lambda: client.metadata.get_cost(**kw)))
            except Exception as ex:  # noqa: BLE001
                msg = f"{type(ex).__name__}: {ex}"
                st["status"] = (f"AUTH_FAILED: {msg[:160]}" if any(t in msg for t in AUTH_ERRORS)
                                else f"ESTIMATE_FAILED: {msg[:160]}")
                break
            if est > MAX_USD_PER_REQUEST + 1e-12 and lane.remaining >= est:
                st["status"] = f"OVER_REQUEST_CAP: {a.date()}..{b.date()} ${est:.2f}"
                break
            if est > lane.remaining + 1e-12:               # the lifetime cap cannot buy this whole year: shorten it
                allow = min(lane.remaining, MAX_USD_PER_REQUEST)
                fit = dbf._fit_range(lambda x, y: dbf._retry(lambda: client.metadata.get_cost(**_kw(root, dataset, x, y))),
                                     a, b, allow, keep="end")
                lane.data["exhausted_before"] = (fit[0] if fit else b).isoformat()
                lane.save()
                if fit is None:
                    st["status"] = "CAP_REACHED"
                    break
                a2, b2, est = fit
                st["trimmed"] = dict(year_start=a.isoformat(), kept_from=a2.isoformat(), estimate_usd=round(est, 4))
                kw = _kw(root, dataset, a2, b2)
            if run_spent + est > MAX_USD_PER_RUN + 1e-12:
                st["status"] = "RUN_LIMIT"                 # continues next run
                break
            try:
                part = dbf.resample_5m(dbf._as_ohlcv_1m(dbf._retry(lambda: client.timeseries.get_range(**kw))))
            except Exception as ex:  # noqa: BLE001
                st["status"] = f"REQUEST_FAILED: {type(ex).__name__}: {ex}"[:200]
                break
            run_spent += est
            lane.record(est, f"{root} {kw['start'][:10]}..{kw['end'][:10]} rows5m={len(part)}", now.isoformat())
            frame = store.merge_frames(frame, part)
            store.save_frame(frame, path)
            st["bought"].append(dict(start=kw["start"], end=kw["end"], usd=round(est, 4), rows_5m=int(len(part))))
            if st["trimmed"]:
                st["status"] = "CAP_REACHED"
                break
        st["spent_usd"] = lane.data["spent_usd"]
        st["history_first"] = frame.index[0].isoformat() if not frame.empty else None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=".cl_cache")
    ap.add_argument("--ledger-dir", default=budget.LEDGER_DIR)
    ap.add_argument("--status", default="automation_intelligence/cl_lab/history_status.json")
    a = ap.parse_args(argv)
    res = run(a.cache, a.ledger_dir)
    os.makedirs(os.path.dirname(os.path.abspath(a.status)), exist_ok=True)
    with open(a.status, "w", encoding="utf-8") as f:
        json.dump(dict(schema="cl_lab.databento_history_status/1", roots=res, execution_authorized=False),
                  f, indent=1, sort_keys=True, default=str)
        f.write("\n")
    print(json.dumps({r: (v["status"], v["spent_usd"]) for r, v in res.items()}))


if __name__ == "__main__":
    main()
