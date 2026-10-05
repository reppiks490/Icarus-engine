# CL (Claude, Anthropic) — 2026-10-05 — leftover Databento credit -> NQ MBP-10 order-book days (owner: "an absolute MUST")
"""Spends each account's leftover credit (``databento_budget.sweep_cap``: estimated remaining credit minus
a small reserve minus everything committed to the account's other lanes) on NQ MBP-10 order-book data.

What is bought: ``NQ.v.0`` MBP-10 for the regular session of a trading day, 09:15-16:15 New York time
(DST-aware), one request per day. Full depth (10 levels) and full resolution are never reduced; when the
money left cannot buy a whole window, the window is shortened from its end in 15-minute steps.

Which days: trading days with a complete RTH session in the NQ OHLCV corpus, newest first, never one
already held by any account. Half of each account's sweep cap is kept for days from the forward period
(>= ``FORWARD_START``) so the R7-E08 resilience test gets out-of-sample book data as those days arrive; the
other half buys the most recent past days now.

What is kept: the raw DBN is streamed to a temporary file, hashed, reduced, and deleted (as in
``databento_depth_acquire``). Two derived caches survive in the depth cache: the 1-minute microstructure
features of ``databento_depth_acquire.summarize_store`` and the event-level resilience rows of
``cl_lab.depth_resilience``. The repository receives only the manifest; no vendor rows are committed."""
from __future__ import annotations

import argparse
import glob
import json
import os
import tempfile
from zoneinfo import ZoneInfo

import pandas as pd

from .. import store
from . import databento as dbf
from . import databento_budget as budget
from . import databento_depth_acquire as acq

ROOT, DATASET, SCHEMA = "NQ", "GLBX.MDP3", "mbp-10"
NY = ZoneInfo("America/New_York")
WINDOW = ("09:15", "16:15")
FORWARD_START = pd.Timestamp("2026-10-05").date()
PAST_SHARE = 0.5
MIN_RTH_BARS = 70
MAX_DAYS_PRICED = 40
STEP = pd.Timedelta(minutes=15)


def window(day) -> tuple[pd.Timestamp, pd.Timestamp]:
    d = pd.Timestamp(day).date()
    a = pd.Timestamp(f"{d} {WINDOW[0]}", tz=NY).tz_convert("UTC")
    b = pd.Timestamp(f"{d} {WINDOW[1]}", tz=NY).tz_convert("UTC")
    return a, b


def kwargs(a: pd.Timestamp, b: pd.Timestamp) -> dict:
    return dict(dataset=DATASET, symbols=dbf.continuous_symbol(ROOT), schema=SCHEMA, stype_in="continuous",
                start=a.isoformat(), end=b.isoformat())


def held_days(depth_cache: str, ledger_dir: str | None = None) -> set[str]:
    """Days already bought by ANY account: reduced files in the cache, plus every day with net spend in a
    sweep ledger (committed to git), so a lost cache can never make a day be bought twice."""
    days = {os.path.basename(p)[:10] for p in glob.glob(os.path.join(depth_cache, "resilience", "*", ROOT.lower(), "*.csv.gz"))}
    for lane in budget.SWEEP_LANES:
        copies = [budget._load(budget._path(b, lane)) for b in (ledger_dir, depth_cache) if b]
        data = max([c for c in copies if c] or [{}], key=lambda c: c.get("spent_usd", 0.0))
        net: dict[str, float] = {}
        for e in data.get("entries", []):
            parts = str(e.get("what", "")).split()
            if len(parts) >= 3 and parts[0] == ROOT and parts[1] == SCHEMA:
                net[parts[2]] = net.get(parts[2], 0.0) + float(e.get("usd", 0.0))
        days |= {d for d, v in net.items() if v > 1e-9}
    return days


def trading_days(cache_dir: str, safe_end: pd.Timestamp) -> list:
    """Days with a complete regular session in the NQ OHLCV corpus whose window ends before ``safe_end``."""
    path = os.path.join(cache_dir, f"databento_{ROOT.lower()}_5m.csv.gz")
    if not os.path.exists(path):
        return []
    f = store.load_frame(path, intraday=True)
    if f is None or f.empty:
        return []
    ny = pd.DatetimeIndex(f.index).tz_convert(NY)
    mins = ny.hour * 60 + ny.minute
    rth = (mins >= 570) & (mins < 960) & (ny.dayofweek < 5)
    counts = pd.Series(1, index=ny.date[rth]).groupby(level=0).size()
    days = [d for d, n in counts.items() if n >= MIN_RTH_BARS and window(d)[1] <= safe_end]
    return sorted(days, reverse=True)


def _fit_end(cost_of, a: pd.Timestamp, b: pd.Timestamp, cap: float):
    """Latest end (15-minute steps, at least one hour) whose estimate fits ``cap``: (end, estimate) or None."""
    ends = list(pd.date_range(a + pd.Timedelta(hours=1), b, freq=STEP))
    best = None
    lo, hi = 0, len(ends) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        est = float(cost_of(a, ends[mid]))
        if est <= cap + 1e-12:
            best, lo = (ends[mid], est), mid + 1
        else:
            hi = mid - 1
    return best


def run_account(account: str, *, cache_dir: str, depth_cache: str, ledger_dir: str = budget.LEDGER_DIR,
                mirrors=(), max_request_usd: float = 15.0, client=None, now=None) -> dict:
    lane_id = next(l for l, a in budget.SWEEP_LANES.items() if a == account)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    out = dict(schema="cl_lab.databento_depth_sweep/1", generated_at=now.isoformat(), account=account, lane=lane_id,
               root=ROOT, dataset=DATASET, data_schema=SCHEMA, window_new_york=list(WINDOW), status="OK", bought=[],
               errors=[], raw_retention="none; temporary DBN is hashed, reduced, and deleted",
               execution_authorized=False, production_decision_authorized=False)
    if client is None and not dbf.account_configured(account):
        out["status"] = f"UNCONFIGURED: {dbf.api_key_env(account)} not set"
        return out
    lane = budget.Lane(lane_id, ledger_dir, mirror=depth_cache, mirrors=mirrors)
    out.update(cap_usd=lane.cfg["cap_usd"], spent_before_usd=lane.data["spent_usd"])
    if lane.remaining <= 0.01:
        out["status"] = "CAP_REACHED"
        return out
    hist = client or dbf.historical_client(account=account)
    safe_end = now - pd.Timedelta(minutes=acq._lag_minutes())
    held = held_days(depth_cache, ledger_dir)
    todo = [d for d in trading_days(cache_dir, safe_end) if str(d) not in held]
    fwd = [d for d in todo if d >= FORWARD_START]
    past = [d for d in todo if d < FORWARD_START]
    priced = 0
    for day in fwd + past:
        if priced >= MAX_DAYS_PRICED or lane.remaining <= 0.01:
            break
        is_past = day < FORWARD_START
        allow = min(lane.remaining, max_request_usd)
        if is_past:
            allow = min(allow, PAST_SHARE * lane.cfg["cap_usd"] - float(lane.data.get("past_spent_usd", 0.0)))
            if allow <= 0.01:
                continue
        a, b = window(day)
        cost_of = lambda x, y: dbf._retry(lambda: hist.metadata.get_cost(**kwargs(x, y)))
        try:
            est = float(cost_of(a, b))
            priced += 1
            if est > allow + 1e-12:
                fit = _fit_end(cost_of, a, b, allow)
                if fit is None:
                    out["errors"].append(dict(day=str(day), status="does_not_fit", estimate_usd=round(est, 4)))
                    if not is_past:
                        continue
                    break
                b, est = fit
        except Exception as ex:  # noqa: BLE001
            msg = f"{type(ex).__name__}: {ex}"
            out["errors"].append(dict(day=str(day), status="estimate_error", error=msg[:200]))
            if any(t in msg for t in ("401", "403", "auth_")):
                out["status"] = f"AUTH_FAILED: {msg[:160]}"
                break
            continue
        res = _buy(hist, account, day, a, b, est, lane, depth_cache, now, is_past)
        (out["bought"] if res.get("status") == "ok" else out["errors"]).append(res)
    out["spent_usd"] = lane.data["spent_usd"]
    out["remaining_usd"] = round(lane.remaining, 4)
    out["past_spent_usd"] = float(lane.data.get("past_spent_usd", 0.0))
    out["held_days"] = sorted(held_days(depth_cache, ledger_dir))
    return out


def _buy(hist, account, day, a, b, est, lane, depth_cache, now, is_past) -> dict:
    base = dict(day=str(day), start=a.isoformat(), end=b.isoformat(), estimated_cost_usd=round(est, 6),
                partial_window=bool(b < window(day)[1]))
    what = f"{ROOT} {SCHEMA} {day} {a.isoformat()[11:16]}-{b.isoformat()[11:16]}Z"
    # Counted BEFORE the request: a run killed mid-download (step timeout) must not leave paid data off
    # the ledger. Reversed below only when not one byte arrived.
    lane.record(est, what, now.isoformat())
    if is_past:
        lane.data["past_spent_usd"] = round(float(lane.data.get("past_spent_usd", 0.0)) + est, 6)
        lane.save()
    raw = None
    try:
        tmpdir = os.path.join(depth_cache, "_raw_tmp")
        os.makedirs(tmpdir, exist_ok=True)
        fd, raw = tempfile.mkstemp(prefix=f"{account}-sweep-{day}-", suffix=".dbn.zst", dir=tmpdir)
        os.close(fd)
        os.remove(raw)                                   # the SDK refuses to stream into an existing file
        dbn = hist.timeseries.get_range(**kwargs(a, b), path=raw)
        raw_sha, raw_bytes = acq._sha256(raw), os.path.getsize(raw)
        from .. import depth_resilience
        ev = depth_resilience.events(dbn)
        feats = acq.summarize_store(dbn)
        if feats.empty:
            raise RuntimeError("MBP-10 request produced no reducible records")
        cand = acq.Candidate(ROOT, DATASET, SCHEMA, str(day), "sweep", 1.0, 1)
        fpath = acq.feature_path(depth_cache, account, cand)
        acq._write_features(feats, fpath)
        rpath = os.path.join(depth_cache, "resilience", account, ROOT.lower(), f"{day}.csv.gz")
        acq._write_features(ev.set_index("ts") if len(ev) else ev, rpath)
        return dict(base, status="ok", raw_sha256=raw_sha, raw_bytes=raw_bytes, raw_retained=False,
                    feature_rows=int(len(feats)), resilience_events=int(len(ev)),
                    sweeps_2plus=int((ev["levels_swept"] >= 2).sum()) if len(ev) else 0)
    except Exception as ex:  # noqa: BLE001
        if not (raw and os.path.exists(raw) and os.path.getsize(raw) > 0):
            lane.record(-est, what + " reversed: no data received", now.isoformat())
            if is_past:
                lane.data["past_spent_usd"] = round(float(lane.data.get("past_spent_usd", 0.0)) - est, 6)
                lane.save()
        return dict(base, status="download_error", error=f"{type(ex).__name__}: {ex}"[:300])
    finally:
        if raw and os.path.exists(raw):
            try:
                os.remove(raw)
            except OSError:
                pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", choices=sorted(set(budget.SWEEP_LANES.values())), required=True)
    ap.add_argument("--cache", default=".cl_cache")
    ap.add_argument("--depth-cache", default=".databento_depth_cache")
    ap.add_argument("--ledger-dir", default=budget.LEDGER_DIR)
    ap.add_argument("--mirror", action="append", default=[], help="other caches holding lane ledger copies")
    ap.add_argument("--max-request-usd", type=float, default=15.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = run_account(a.account, cache_dir=a.cache, depth_cache=a.depth_cache, ledger_dir=a.ledger_dir,
                      mirrors=[a.cache, *a.mirror], max_request_usd=a.max_request_usd)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, sort_keys=True, default=str)
        f.write("\n")
    print(json.dumps({k: res.get(k) for k in ("account", "status", "cap_usd", "spent_usd", "remaining_usd")}
                     | {"bought": len(res["bought"]), "errors": len(res["errors"])}))


if __name__ == "__main__":
    main()
