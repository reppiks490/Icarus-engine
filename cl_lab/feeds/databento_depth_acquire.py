# ChatGPT — 2026-10-04 — Databento cost-gated depth corpus acquisition
"""Acquire high-value MBO/MBP-10 slices under explicit per-account budgets.

This is a research data pipeline, never an execution path.

Properties:
- credentials are isolated; there is no fallback/rotation across accounts;
- every request is priced with metadata.get_cost() before any download;
- both per-request and total estimated-spend caps are enforced;
- already-cached slices are never downloaded again;
- day selection is regime-diverse using the broad OHLCV cache when available;
- raw DBN is streamed to a temporary file, hashed, reduced to compact minute
  microstructure features, then deleted;
- only derived feature caches and compact provenance manifests survive;
- no raw licensed order-book rows are committed to git.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from .. import store
from . import databento as dbfeed
from . import databento_budget as budget

HISTORICAL_LAG_DEFAULT_MINUTES = 500

# Profile membership is intentionally non-overlapping at the account level.
# The second/third accounts are budget pools supplied by the user, not automatic
# fallbacks for each other.
PROFILES = {
    "index": {
        "account": "secondary",
        "instruments": (
            ("NQ", "GLBX.MDP3", "mbo", 1.00, 12),
            ("MNQ", "GLBX.MDP3", "mbo", 0.98, 12),
            ("ES", "GLBX.MDP3", "mbo", 0.92, 8),
            ("MES", "GLBX.MDP3", "mbo", 0.90, 8),
            ("RTY", "GLBX.MDP3", "mbp-10", 0.74, 6),
            ("M2K", "GLBX.MDP3", "mbp-10", 0.72, 6),
            ("YM", "GLBX.MDP3", "mbp-10", 0.68, 5),
            ("MYM", "GLBX.MDP3", "mbp-10", 0.66, 5),
        ),
    },
    "diversifier": {
        "account": "third",
        "instruments": (
            ("GC", "GLBX.MDP3", "mbo", 0.90, 8),
            ("MGC", "GLBX.MDP3", "mbo", 0.88, 8),
            ("SI", "GLBX.MDP3", "mbo", 0.76, 6),
            ("SIL", "GLBX.MDP3", "mbo", 0.74, 6),
            ("BTC", "GLBX.MDP3", "mbo", 0.70, 5),
            ("MBT", "GLBX.MDP3", "mbo", 0.68, 5),
            ("PL", "GLBX.MDP3", "mbp-10", 0.52, 4),
            ("PA", "GLBX.MDP3", "mbp-10", 0.50, 4),
            # Cross-asset context. CFE/ICE depth can be materially more
            # expensive than CME, so these begin as MBP-10 rather than MBO.
            ("VX", "XCBF.PITCH", "mbp-10", 0.86, 5),
            ("VXM", "XCBF.PITCH", "mbp-10", 0.80, 4),
            ("ZN", "GLBX.MDP3", "mbp-10", 0.78, 5),
            ("DX", "IFUS.IMPACT", "mbp-10", 0.72, 4),
        ),
    },
}

ROLE_WEIGHT = {
    "high_range_1": 1.35,
    "high_range_2": 1.28,
    "high_volume_1": 1.24,
    "high_volume_2": 1.18,
    "upper_quartile": 1.10,
    "median": 1.00,
    "lower_quartile": 0.98,
    "quiet": 0.96,
    "recent": 1.06,
}


@dataclass(frozen=True)
class Candidate:
    root: str
    dataset: str
    schema: str
    day: str
    role: str
    priority: float
    target_days: int

    @property
    def value(self) -> float:
        return self.priority * ROLE_WEIGHT.get(self.role, 1.0)


def _safe_now(now: Any = None) -> pd.Timestamp:
    x = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    return x.tz_localize("UTC") if x.tzinfo is None else x.tz_convert("UTC")


def _lag_minutes() -> int:
    try:
        value = int(os.environ.get("CL_DATABENTO_HISTORICAL_LAG_MINUTES") or str(HISTORICAL_LAG_DEFAULT_MINUTES))
    except ValueError as ex:
        raise ValueError("CL_DATABENTO_HISTORICAL_LAG_MINUTES must be an integer") from ex
    if value < 0:
        raise ValueError("CL_DATABENTO_HISTORICAL_LAG_MINUTES must be >= 0")
    return value


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _feed_path(cache_dir: str, root: str) -> str:
    return os.path.join(cache_dir, f"databento_{root.lower()}_5m.csv.gz")


def _daily_regimes(cache_dir: str, root: str, safe_end: pd.Timestamp) -> pd.DataFrame:
    path = _feed_path(cache_dir, root)
    if not os.path.exists(path):
        return pd.DataFrame()
    frame = store.load_frame(path, intraday=True)
    if frame is None or frame.empty:
        return pd.DataFrame()
    x = frame.copy()
    x.index = pd.to_datetime(x.index, utc=True)
    x = x[x.index < safe_end]
    if x.empty:
        return pd.DataFrame()
    x["day"] = x.index.date
    g = x.groupby("day", sort=True)
    d = pd.DataFrame({
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].median(),
        "volume": g["volume"].sum(),
        "bars": g.size(),
    })
    d["range_pct"] = (d["high"] - d["low"]) / d["close"].abs().replace(0, float("nan"))
    d = d.replace([float("inf"), float("-inf")], float("nan")).dropna(subset=["range_pct"])
    # A UTC day with less than one hour of 5m bars is not a useful regime sample.
    return d[d["bars"] >= 12]


def _nearest_quantile(d: pd.DataFrame, q: float) -> str | None:
    if d.empty:
        return None
    target = float(d["range_pct"].quantile(q))
    idx = (d["range_pct"] - target).abs().idxmin()
    return str(idx)


def informative_days(cache_dir: str, root: str, target_days: int, now: Any = None) -> list[tuple[str, str]]:
    """Select high/normal/quiet/recent complete days without hindsight labels."""
    now = _safe_now(now)
    lag = _lag_minutes()
    safe_clock = now - pd.Timedelta(minutes=lag)
    # Request whole UTC days only. At 01:00 UTC with an 8h historical lag, this
    # deliberately ends two calendar dates back rather than touching unavailable
    # same-day/live data.
    safe_end = safe_clock.floor("D")
    d = _daily_regimes(cache_dir, root, safe_end)
    target_days = max(1, int(target_days))
    picked: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(day: Any, role: str) -> None:
        if day is None or len(picked) >= target_days:
            return
        ds = str(day)
        if ds not in seen:
            seen.add(ds)
            picked.append((ds, role))

    if not d.empty:
        high_range = d.sort_values(["range_pct", "volume"], ascending=[False, False])
        if len(high_range):
            add(high_range.index[0], "high_range_1")
        if len(high_range) > 1:
            add(high_range.index[1], "high_range_2")

        high_volume = d.sort_values(["volume", "range_pct"], ascending=[False, False])
        if len(high_volume):
            add(high_volume.index[0], "high_volume_1")
        if len(high_volume) > 1:
            add(high_volume.index[1], "high_volume_2")

        add(_nearest_quantile(d, 0.75), "upper_quartile")
        add(_nearest_quantile(d, 0.50), "median")
        add(_nearest_quantile(d, 0.25), "lower_quartile")
        quiet = d.sort_values(["range_pct", "volume"], ascending=[True, True])
        if len(quiet):
            add(quiet.index[0], "quiet")

        for day in d.sort_index(ascending=False).index:
            add(day, "recent")
            if len(picked) >= target_days:
                break

    # Empty-cache fallback: use recent complete weekdays, still behind the
    # historical watermark. Once OHLCV arrives, subsequent runs replace this
    # crude fallback with regime-diverse selection for new uncached slices.
    day = safe_end - pd.Timedelta(days=1)
    guard = 0
    while len(picked) < target_days and guard < 40:
        if day.dayofweek < 5:
            add(day.date(), "recent")
        day -= pd.Timedelta(days=1)
        guard += 1
    return picked


def profile_candidates(profile: str, cache_dir: str, now: Any = None) -> list[Candidate]:
    cfg = PROFILES.get(profile)
    if cfg is None:
        raise ValueError(f"unknown depth profile {profile!r}")
    out: list[Candidate] = []
    for root, dataset, schema, priority, target_days in cfg["instruments"]:
        for day, role in informative_days(cache_dir, root, target_days, now):
            out.append(Candidate(root, dataset, schema, day, role, float(priority), int(target_days)))
    return out


def request_kwargs(c: Candidate) -> dict[str, Any]:
    start = pd.Timestamp(c.day, tz="UTC")
    end = start + pd.Timedelta(days=1)
    return {
        "dataset": c.dataset,
        "symbols": dbfeed.continuous_symbol(c.root),
        "schema": c.schema,
        "stype_in": "continuous",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def feature_path(depth_cache: str, account: str, c: Candidate) -> str:
    schema = c.schema.replace("-", "")
    return os.path.join(depth_cache, "features", account, schema, c.root.lower(), f"{c.day}.csv.gz")


def price_candidates(
    client: Any,
    account: str,
    candidates: Iterable[Candidate],
    depth_cache: str,
    max_request_usd: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    priced: list[dict[str, Any]] = []
    cached: list[dict[str, Any]] = []
    cap = float(max_request_usd)
    if cap < 0:
        raise ValueError("max_request_usd must be >= 0")
    for c in candidates:
        fpath = feature_path(depth_cache, account, c)
        base = {
            "root": c.root,
            "dataset": c.dataset,
            "schema": c.schema,
            "day": c.day,
            "role": c.role,
            "priority": c.priority,
            "value_score": c.value,
            "symbol": dbfeed.continuous_symbol(c.root),
        }
        if os.path.exists(fpath):
            cached.append({
                **base,
                "status": "cached",
                "request_performed": False,
                "feature_path": os.path.relpath(fpath, depth_cache),
                "feature_sha256": _sha256(fpath),
                "feature_bytes": os.path.getsize(fpath),
            })
            continue
        try:
            cost = float(client.metadata.get_cost(**request_kwargs(c)))
            row = {
                **base,
                "estimated_cost_usd": cost,
                "value_per_usd": c.value / max(cost, 1e-12),
                "request_performed": False,
                "status": "ok" if cost <= cap + 1e-12 else "blocked_per_request_cap",
            }
        except Exception as ex:
            row = {
                **base,
                "status": "estimate_error",
                "request_performed": False,
                "error": f"{type(ex).__name__}: {ex}",
            }
        priced.append(row)
    return priced, cached


def allocate(priced: list[dict[str, Any]], budget_usd: float) -> list[dict[str, Any]]:
    """Breadth-first, then highest information-density, under one hard budget."""
    budget = float(budget_usd)
    if budget < 0:
        raise ValueError("budget_usd must be >= 0")
    ok = [dict(x) for x in priced if x.get("status") == "ok"]
    selected: list[dict[str, Any]] = []
    used: set[tuple[str, str, str]] = set()
    spent = 0.0

    # First try to buy one representative day per root, ordered by research
    # priority. This prevents one very cheap market from consuming the full pool.
    by_root: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ok:
        by_root[str(row["root"])].append(row)
    for rows in by_root.values():
        rows.sort(key=lambda r: (-float(r["value_per_usd"]), -float(r["value_score"]), r["day"]))
    roots = sorted(by_root, key=lambda r: (-max(float(x["priority"]) for x in by_root[r]), r))
    for root in roots:
        row = by_root[root][0]
        cost = float(row["estimated_cost_usd"])
        if spent + cost <= budget + 1e-12:
            selected.append(row)
            used.add((row["root"], row["schema"], row["day"]))
            spent += cost

    rest = [r for r in ok if (r["root"], r["schema"], r["day"]) not in used]
    rest.sort(key=lambda r: (-float(r["value_per_usd"]), -float(r["value_score"]), r["root"], r["day"]))
    for row in rest:
        cost = float(row["estimated_cost_usd"])
        if spent + cost <= budget + 1e-12:
            selected.append(row)
            spent += cost
    return selected


def _action(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    if len(s) == 1:
        return s.upper()
    s2 = s.upper()
    for code, word in (("A", "ADD"), ("C", "CANCEL"), ("M", "MODIFY"), ("R", "CLEAR"), ("T", "TRADE"), ("F", "FILL")):
        if word in s2:
            return code
    return s2[:1]


def _side(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).upper()
    if len(s) == 1:
        return s
    if "BID" in s or "BUY" in s:
        return "B"
    if "ASK" in s or "SELL" in s:
        return "A"
    return s[:1]


def _price(record: Any, field: str = "price") -> float | None:
    pretty = getattr(record, f"pretty_{field}", None)
    if pretty is not None:
        try:
            x = float(pretty)
            return x if math.isfinite(x) else None
        except Exception:
            pass
    raw = getattr(record, field, None)
    if raw is None:
        return None
    try:
        raw_i = int(raw)
        if raw_i == (1 << 63) - 1:
            return None
        x = raw_i / 1_000_000_000.0
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _level_price(level: Any, field: str) -> float | None:
    pretty = getattr(level, f"pretty_{field}", None)
    if pretty is not None:
        try:
            x = float(pretty)
            return x if math.isfinite(x) else None
        except Exception:
            pass
    raw = getattr(level, field, None)
    if raw is None:
        return None
    try:
        raw_i = int(raw)
        if raw_i == (1 << 63) - 1:
            return None
        return raw_i / 1_000_000_000.0
    except Exception:
        return None


def summarize_store(dbn_store: Any) -> pd.DataFrame:
    """Streaming one-minute microstructure feature reduction."""
    b: dict[int, dict[str, Any]] = {}

    def get_bucket(minute_ns: int) -> dict[str, Any]:
        if minute_ns not in b:
            b[minute_ns] = {
                "events": 0, "add_events": 0, "cancel_events": 0,
                "modify_events": 0, "trade_events": 0, "fill_events": 0,
                "other_events": 0, "event_size": 0, "add_size": 0,
                "cancel_size": 0, "trade_size": 0, "bid_size": 0,
                "ask_size": 0, "bid_events": 0, "ask_events": 0,
                "latency_sum_ns": 0, "latency_count": 0, "latency_max_ns": 0,
                "price_min": None, "price_max": None,
                "spread_sum": 0.0, "spread_count": 0,
                "depth10_bid_sum": 0, "depth10_ask_sum": 0, "depth10_count": 0,
            }
        return b[minute_ns]

    for rec in dbn_store:
        ts_recv = getattr(rec, "ts_recv", None)
        ts_event = getattr(rec, "ts_event", None)
        raw_ts = ts_recv if ts_recv is not None else ts_event
        if raw_ts is None:
            continue
        try:
            ts_ns = int(raw_ts)
        except Exception:
            continue
        minute_ns = (ts_ns // 60_000_000_000) * 60_000_000_000
        row = get_bucket(minute_ns)
        row["events"] += 1

        action = _action(getattr(rec, "action", None))
        side = _side(getattr(rec, "side", None))
        try:
            size = max(0, int(getattr(rec, "size", 0) or 0))
        except Exception:
            size = 0
        row["event_size"] += size
        if action == "A":
            row["add_events"] += 1
            row["add_size"] += size
        elif action == "C":
            row["cancel_events"] += 1
            row["cancel_size"] += size
        elif action == "M":
            row["modify_events"] += 1
        elif action == "T":
            row["trade_events"] += 1
            row["trade_size"] += size
        elif action == "F":
            row["fill_events"] += 1
        else:
            row["other_events"] += 1
        if side == "B":
            row["bid_events"] += 1
            row["bid_size"] += size
        elif side == "A":
            row["ask_events"] += 1
            row["ask_size"] += size

        if ts_recv is not None and ts_event is not None:
            try:
                latency = max(0, int(ts_recv) - int(ts_event))
                row["latency_sum_ns"] += latency
                row["latency_count"] += 1
                row["latency_max_ns"] = max(row["latency_max_ns"], latency)
            except Exception:
                pass

        px = _price(rec)
        if px is not None:
            row["price_min"] = px if row["price_min"] is None else min(row["price_min"], px)
            row["price_max"] = px if row["price_max"] is None else max(row["price_max"], px)

        levels = getattr(rec, "levels", None)
        if levels is not None:
            try:
                lvls = list(levels)[:10]
            except Exception:
                lvls = []
            if lvls:
                bid = _level_price(lvls[0], "bid_px")
                ask = _level_price(lvls[0], "ask_px")
                if bid is not None and ask is not None and ask >= bid:
                    row["spread_sum"] += ask - bid
                    row["spread_count"] += 1
                bid_sum = ask_sum = 0
                for lvl in lvls:
                    try:
                        bid_sum += max(0, int(getattr(lvl, "bid_sz", 0) or 0))
                        ask_sum += max(0, int(getattr(lvl, "ask_sz", 0) or 0))
                    except Exception:
                        pass
                row["depth10_bid_sum"] += bid_sum
                row["depth10_ask_sum"] += ask_sum
                row["depth10_count"] += 1

    rows: list[dict[str, Any]] = []
    for minute_ns in sorted(b):
        x = dict(b[minute_ns])
        x["ts_minute"] = pd.Timestamp(minute_ns, unit="ns", tz="UTC").isoformat()
        x["latency_mean_ns"] = x["latency_sum_ns"] / x["latency_count"] if x["latency_count"] else None
        x["spread_mean"] = x["spread_sum"] / x["spread_count"] if x["spread_count"] else None
        x["depth10_bid_mean"] = x["depth10_bid_sum"] / x["depth10_count"] if x["depth10_count"] else None
        x["depth10_ask_mean"] = x["depth10_ask_sum"] / x["depth10_count"] if x["depth10_count"] else None
        denom = x["bid_size"] + x["ask_size"]
        x["event_size_imbalance"] = (x["bid_size"] - x["ask_size"]) / denom if denom else None
        x["cancel_add_size_ratio"] = x["cancel_size"] / x["add_size"] if x["add_size"] else None
        rows.append(x)
    return pd.DataFrame(rows).set_index("ts_minute") if rows else pd.DataFrame()


def _write_features(frame: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        frame.to_csv(f)
    os.replace(tmp, path)


def acquire_profile(
    *,
    profile: str,
    cache_dir: str,
    depth_cache: str,
    budget_usd: float,
    max_request_usd: float,
    now: Any = None,
    client: Any = None,
    ledger_dir: str | None = None,
) -> dict[str, Any]:
    cfg = PROFILES.get(profile)
    if cfg is None:
        raise ValueError(f"unknown depth profile {profile!r}")
    account = str(cfg["account"])
    if client is None and not dbfeed.account_configured(account):
        return {
            "schema": "cl_lab.databento_depth_corpus/1",
            "status": "unconfigured",
            "profile": profile,
            "account": account,
            "error": f"{dbfeed.api_key_env(account)} not configured",
            "requests": [],
            "execution_authorized": False,
            "production_decision_authorized": False,
        }
    hist = client or dbfeed.historical_client(account=account)
    # CL 2026-10-05, owner's credit split: --budget-usd is per run, so without a lifetime ledger every run
    # (several a day) could buy up to the full budget again on new days. Cap each run at what the lane has left.
    lane = budget.Lane({"index": "depth:index", "diversifier": "depth:diversifier"}[profile],
                       ledger_dir, mirror=depth_cache) if ledger_dir else None
    if lane is not None:
        budget_usd = min(float(budget_usd), lane.remaining)
    candidates = profile_candidates(profile, cache_dir, now)
    priced, cached = price_candidates(hist, account, candidates, depth_cache, max_request_usd)
    selected = allocate(priced, budget_usd)
    selected_keys = {(x["root"], x["schema"], x["day"]) for x in selected}
    rows = list(cached)
    estimated_selected = sum(float(x["estimated_cost_usd"]) for x in selected)
    estimated_requested = 0.0

    # Preserve all price/blocked/error evidence, even when not selected.
    for r in priced:
        key = (r["root"], r["schema"], r["day"])
        if key not in selected_keys:
            rows.append({**r, "selected": False})

    for r in selected:
        c = Candidate(
            root=str(r["root"]), dataset=str(r["dataset"]), schema=str(r["schema"]),
            day=str(r["day"]), role=str(r["role"]), priority=float(r["priority"]),
            target_days=1,
        )
        fpath = feature_path(depth_cache, account, c)
        base = {**r, "selected": True}
        raw_path = None
        try:
            os.makedirs(os.path.join(depth_cache, "_raw_tmp"), exist_ok=True)
            fd, raw_path = tempfile.mkstemp(
                prefix=f"{account}-{c.root}-{c.day}-",
                suffix=".dbn.zst",
                dir=os.path.join(depth_cache, "_raw_tmp"),
            )
            os.close(fd)
            os.remove(raw_path)   # CL: the SDK refuses to stream into an existing file (FileExistsError, 2026-10-05)
            # Count the full preflight estimate conservatively before the API call:
            # a transport failure after request acceptance must not make the ledger
            # look cheaper than the spend we authorized.
            estimated_requested += float(r["estimated_cost_usd"])
            if lane is not None:   # CL 2026-10-05: charged BEFORE the request, so a killed run cannot under-count
                lane.record(float(r["estimated_cost_usd"]), f"{c.root} {c.schema} {c.day}",
                            pd.Timestamp.now(tz="UTC").isoformat())
            # SDK streams the response to path while returning a replayable DBNStore.
            dbn = hist.timeseries.get_range(**request_kwargs(c), path=raw_path)
            raw_sha = _sha256(raw_path)
            raw_bytes = os.path.getsize(raw_path)
            features = summarize_store(dbn)
            if features.empty:
                raise RuntimeError("depth request produced no reducible records")
            _write_features(features, fpath)
            rows.append({
                **base,
                "status": "ok",
                "request_performed": True,
                "estimated_cost_usd": float(r["estimated_cost_usd"]),
                "raw_sha256": raw_sha,
                "raw_bytes": raw_bytes,
                "raw_retained": False,
                "feature_path": os.path.relpath(fpath, depth_cache),
                "feature_sha256": _sha256(fpath),
                "feature_bytes": os.path.getsize(fpath),
                "feature_rows": int(len(features)),
                "feature_first": str(features.index[0]),
                "feature_last": str(features.index[-1]),
            })
        except Exception as ex:
            if lane is not None and any(e.get("what") == f"{c.root} {c.schema} {c.day}" for e in lane.data.get("entries", [])[-1:]) \
                    and not (raw_path and os.path.exists(raw_path) and os.path.getsize(raw_path) > 0):
                lane.record(-float(r["estimated_cost_usd"]), f"{c.root} {c.schema} {c.day} reversed: no data received",
                            pd.Timestamp.now(tz="UTC").isoformat())   # not one byte arrived: nothing was billed
            rows.append({
                **base,
                "status": "download_error",
                "request_performed": raw_path is not None and os.path.exists(raw_path),
                "error": f"{type(ex).__name__}: {ex}",
            })
        finally:
            if raw_path and os.path.exists(raw_path):
                try:
                    os.remove(raw_path)
                except OSError:
                    pass

    ok_downloads = [x for x in rows if x.get("status") == "ok" and x.get("request_performed")]
    return {
        "schema": "cl_lab.databento_depth_corpus/1",
        "status": "ok" if ok_downloads or cached else ("blocked" if selected else "no_eligible_requests"),
        "generated_at": _safe_now(now).isoformat(),
        "profile": profile,
        "account": account,
        "credential_env": dbfeed.api_key_env(account),
        "budget_usd": float(budget_usd),
        "lane": (dict(id=lane.lane, cap_usd=lane.cfg["cap_usd"], spent_usd=lane.data["spent_usd"]) if lane is not None else None),
        "max_request_usd": float(max_request_usd),
        "estimated_selected_usd": estimated_selected,
        "estimated_requested_usd": estimated_requested,
        "downloaded_slices": len(ok_downloads),
        "cached_slices": len(cached),
        "raw_retention": "none; temporary DBN is hashed, reduced, and deleted",
        "feature_resolution": "1 minute",
        "selection_method": "breadth-first then regime-weighted information-per-dollar",
        "requests": sorted(rows, key=lambda x: (x.get("root", ""), x.get("day", ""), x.get("schema", ""), x.get("status", ""))),
        "execution_authorized": False,
        "production_decision_authorized": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=sorted(PROFILES), required=True)
    ap.add_argument("--cache", default=".cl_cache")
    ap.add_argument("--depth-cache", default=".databento_depth_cache")
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget-usd", type=float, default=95.0)
    ap.add_argument("--max-request-usd", type=float, default=15.0)
    ap.add_argument("--ledger-dir", default=budget.LEDGER_DIR)
    a = ap.parse_args(argv)
    result = acquire_profile(
        profile=a.profile,
        cache_dir=a.cache,
        depth_cache=a.depth_cache,
        budget_usd=a.budget_usd,
        max_request_usd=a.max_request_usd,
        ledger_dir=a.ledger_dir,
    )
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, sort_keys=True)
        f.write("\n")
    print(json.dumps({
        "status": result["status"],
        "profile": result["profile"],
        "account": result["account"],
        "estimated_requested_usd": result.get("estimated_requested_usd", 0.0),
        "downloaded_slices": result.get("downloaded_slices", 0),
        "cached_slices": result.get("cached_slices", 0),
    }))


if __name__ == "__main__":
    main()
