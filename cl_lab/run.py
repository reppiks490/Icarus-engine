# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.run: one lab cycle (data -> grammar -> gates -> registry) with 1:1 persistence
"""python -m cl_lab.run --out automation_intelligence/cl_lab --cache .cl_cache

Persistence follows automation_intelligence/README.md: heartbeat.json is the only
mutable in-progress marker; history/<RUN_ID>.json is immutable; latest.json is
replaced only after the history write is read back and verified. RUN_ID is a
deterministic function of the inputs (data identity + grammar + gates + CL code),
so an unchanged input set is a no-op instead of a duplicate logical run.
Research only: execution_authorized and production_decision_authorized are False.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
from datetime import date

import pandas as pd

from . import (EXECUTION_AUTHORIZED, LAB_VERSION, LANE, backtest, bars, boos, corpus, costs, explore, external, grammar,
               hypotheses,
               extend, hypotheses_r2, integrity, ml, pulse_track, registry, sessions, store, validate)

ASSETS = {
    "MNQ": dict(kind="csv", path="data/mnq_5m_full.csv", cost=costs.MNQ, stress=costs.MNQ_STRESS,
                metric="points", weekdays_only=False, continuous_futures=True, index_feed="fred_nasdaq100",
                extension_feed="databento_mnq_5m"),
    "BTCUSDT": dict(kind="cache", feed="btcusdt_5m", cost=costs.CRYPTO_PERP, stress=costs.CRYPTO_PERP_STRESS,
                    metric="returns", weekdays_only=True),
    "ETHUSDT": dict(kind="cache", feed="ethusdt_5m", cost=costs.CRYPTO_PERP, stress=costs.CRYPTO_PERP_STRESS,
                    metric="returns", weekdays_only=True),
}
FORWARD_START = date(2026, 10, 5)  # first CL registration; sessions on/after this date are never tuned on
PREREG_R2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prereg_r2.json")


def _extension(cache_dir, feed):
    p = os.path.join(cache_dir, f"{feed}.csv.gz")
    return store.load_frame(p) if os.path.exists(p) else None


def _daily_feed(cache_dir, feed, col):
    p = os.path.join(cache_dir, f"{feed}.csv.gz")
    if not os.path.exists(p):
        return None
    ext = store.load_frame(p, intraday=False)
    return ext[col].dropna() if col in ext else None


def _sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _code_identity():
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(here, "**", "*.py"), recursive=True)):
        h.update(os.path.relpath(p, here).encode())
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def _git_commit():
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)
    with open(path, "rb") as f:
        back = f.read()
    if back != data.encode():
        raise IOError(f"readback mismatch for {path}")
    return hashlib.sha256(back).hexdigest()


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _economic_events_ui(out_dir, now, limit=12):
    """Compact, causal event-clock projection for the ICARUS UI feed.

    Exact countdowns are emitted only when the official source supplied a timestamp.
    Date-only events (notably FOMC decisions in the current source) remain date-only.
    """
    manifest = _read_json(os.path.join(out_dir, "economic_events_manifest.json"), {}) or {}
    payload = _read_json(os.path.join(out_dir, "economic_events_upcoming.json"), {}) or {}
    events = payload.get("events") or []
    if not manifest or not events:
        return dict(status="UNAVAILABLE", reason="economic event clock has not produced a usable manifest yet",
                    source_status=(manifest.get("sources") or {}))

    now = pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    local_day = now.tz_convert("America/New_York").date()
    future = []
    for raw in events:
        row = {k: raw.get(k) for k in (
            "source", "event_key", "title", "category", "impact", "reference_period",
            "event_date", "scheduled_at_et", "scheduled_at_utc", "time_known", "timing_basis")}
        exact = pd.to_datetime(row.get("scheduled_at_utc"), errors="coerce", utc=True)
        if pd.notna(exact):
            if exact < now:
                continue
            minutes = (exact - now).total_seconds() / 60.0
            row["minutes_to_event"] = round(float(minutes), 1)
            row["_sort"] = exact.value
        else:
            try:
                d = pd.Timestamp(row.get("event_date")).date()
            except Exception:
                continue
            if d < local_day:
                continue
            row["minutes_to_event"] = None
            # Date-only events sort after exact events on the same UTC day.
            row["_sort"] = pd.Timestamp(d, tz="America/New_York").tz_convert("UTC").value + 86_399_000_000_000
        future.append(row)

    future.sort(key=lambda x: (x["_sort"], x.get("source") or "", x.get("title") or ""))
    for row in future:
        row.pop("_sort", None)
    focus = future[:int(limit)]
    high = [x for x in future if x.get("impact") == "high"]
    next_high = high[0] if high else None
    exact_24h = [x for x in high if x.get("minutes_to_event") is not None and 0 <= x["minutes_to_event"] <= 1440]
    source_status = {
        k: {kk: vv for kk, vv in v.items() if kk in ("status", "rows", "transport", "error")}
        for k, v in (manifest.get("sources") or {}).items()
    }
    return dict(
        status="ok",
        generated_at=manifest.get("generated_at"),
        source_status=source_status,
        current_events=manifest.get("current_events"),
        schedule_versions=manifest.get("schedule_versions"),
        high_impact_current=manifest.get("high_impact_current"),
        time_known_current=manifest.get("time_known_current"),
        causality=manifest.get("causality"),
        next_high_impact=next_high,
        high_impact_within_24h=len(exact_24h),
        upcoming=focus,
    )


def load_asset(name, cfg, cache_dir):
    if cfg["kind"] == "csv":
        if not os.path.exists(cfg["path"]):
            return None, dict(status="UNAVAILABLE", reason=f"missing {cfg['path']}")
        df = bars.load_csv(cfg["path"])
        ident = dict(status="OK", source=cfg["path"], sha256=_sha_file(cfg["path"]))
        tb = None
        if cfg.get("extension_feed"):
            ext = _extension(cache_dir, cfg["extension_feed"])
            df, prov = extend.splice(df, ext)
            ident["tape"] = prov
            if prov.get("extension") and prov["extension"].get("rows"):
                ident["extension_sha256"] = store.sha256_frame(df[df.index > pd.Timestamp(prov["base"]["last"])])
                ident["instrument_switches"] = extend.instrument_switches(ext)
    else:
        path = os.path.join(cache_dir, f"{cfg['feed']}.csv.gz")
        df = store.load_frame(path) if os.path.exists(path) else pd.DataFrame()
        if df.empty:
            return None, dict(status="UNAVAILABLE", reason=f"no cached feed {cfg['feed']}")
        tb = df["taker_buy_volume"].astype(float) if "taker_buy_volume" in df else None
        df = df[list(bars.COLUMNS)].astype(float)
        ident = dict(status="OK", source=f"cache:{cfg['feed']}", sha256=store.sha256_frame(df))
    ident.update(rows=int(len(df)), first=df.index[0].isoformat(), last=df.index[-1].isoformat())
    adf = bars.annotate(df)
    rolls, index_close = [], None
    if cfg.get("continuous_futures"):
        index_close = _daily_feed(cache_dir, cfg["index_feed"], "NASDAQ100")
        rolls = integrity.detect_rolls(adf, index_close)
        adf = integrity.back_adjust(adf, rolls)
        ident["integrity"] = integrity.summary(rolls)
    if tb is not None:
        adf["taker_buy_volume"] = tb.reindex(adf.index).to_numpy()
    if cfg["weekdays_only"]:
        adf = adf[pd.to_datetime(adf["session_date"]).dt.dayofweek < 5]
    sess = sessions.build_sessions(adf)
    sess.cache["ml_kind"] = "futures" if cfg["kind"] == "csv" else "crypto"
    if cfg.get("continuous_futures"):
        integrity.mark_sessions(sess, rolls)
        sess.cache["rolls"] = rolls
        ident["integrity"]["basis_check"] = integrity.basis_check(sess, index_close)
    if "taker_buy_volume" in adf:
        sess.cache["TB"] = sessions.slot_array(sess, adf, "taker_buy_volume")
    for feed, col in (("cboe_vix", "VIX_close"), ("cboe_vix9d", "VIX9D_close")):  # causal day conditioners
        p = os.path.join(cache_dir, f"{feed}.csv.gz")
        if os.path.exists(p):
            ext = store.load_frame(p, intraday=False)
            if col in ext:
                sess.cache[("ext", col)] = ext[col]
    return sess, ident


def boos_section(out_dir, cache_dir, external_dir):
    """cl-boos1 (docs/CL_PREREG_R5.md): fixed families re-run on NQ 2010-06 -> 2024-09; recomputed only
    when the history, the external breadth inputs or the lab code change."""
    p = os.path.join(cache_dir, "databento_hist_nq_5m.csv.gz")
    if not os.path.exists(p):
        return dict(status="UNAVAILABLE", protocol=boos.BOOS_VERSION,
                    reason="NQ history not cached yet (backfill on key #3, cl_lab/feeds/databento_history.py)")
    closes = external.tiingo_closes(external_dir) if external_dir and os.path.isdir(external_dir) else pd.DataFrame()
    br = external.breadth(closes)
    fp = hashlib.sha256((_sha_file(p) + _code_identity() + store.sha256_frame(br.to_frame()) if len(br) else
                         _sha_file(p) + _code_identity()).encode()).hexdigest()
    cached = _read_json(os.path.join(out_dir, "boos_latest.json"), {})
    if cached.get("fingerprint") == fp:
        return cached
    raw = store.load_frame(p)
    df = raw[list(bars.COLUMNS)].astype(float)
    if "instrument_id" in raw.columns:            # cl-data-3: exact roll points on the Databento history
        df["instrument_id"] = pd.to_numeric(raw["instrument_id"], errors="coerce")
    adf = bars.annotate(df)
    ndx = _daily_feed(cache_dir, "fred_nasdaq100", "NASDAQ100")
    rolls = integrity.detect_rolls(adf, ndx)
    adf = integrity.back_adjust(adf, rolls)
    sess = sessions.build_sessions(adf)
    integrity.mark_sessions(sess, rolls)
    sess.cache["ml_kind"] = "futures"
    for feed, col in (("cboe_vix", "VIX_close"), ("cboe_vix9d", "VIX9D_close")):
        q = os.path.join(cache_dir, f"{feed}.csv.gz")
        if os.path.exists(q):
            ext = store.load_frame(q, intraday=False)
            if col in ext:
                sess.cache[("ext", col)] = ext[col]
    if len(br):
        sess.cache[("ext", "MEGA8_UP_FRAC")] = br
    fams = [("cl-g1", grammar.enumerate_candidates(), backtest.run), ("cl-r1", hypotheses.CANDIDATES, hypotheses.run_r),
            ("cl-r2/A", hypotheses_r2.A_CANDIDATES, hypotheses_r2.run_a), ("cl-ml1", ml.CANDIDATES, ml.run_m),
            ("cl-r6", boos.R6_CANDIDATES, boos.run_r6)]
    families, lines = {}, []
    for name, cands, fn in fams:
        recs, diag = boos.evaluate(sess, cands, fn, costs.NQ, costs.NQ_STRESS, name)
        families[name] = dict(diagnostics=diag, confirmed=[r for r in recs if r["status"] == "BOOS_CONFIRMED"],
                              top=sorted(recs, key=lambda r: -(r["nw_t"] if r["nw_t"] is not None else -99))[:10])
        lines += [json.dumps(r, sort_keys=True, default=str) for r in recs]
    with open(os.path.join(out_dir, "boos_records.jsonl.tmp"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(os.path.join(out_dir, "boos_records.jsonl.tmp"), os.path.join(out_dir, "boos_records.jsonl"))
    out = dict(schema="cl_lab.boos/1", status="EVALUATED", protocol=boos.BOOS_VERSION, fingerprint=fp,
               window=[str(boos.WINDOW[0].date()), str(boos.WINDOW[1].date())], sessions=int(sess.D),
               first=str(sess.dates[0]), last=str(sess.dates[-1]), breadth_available=bool(len(br)),
               integrity=dict(integrity.summary(rolls), basis_check=integrity.basis_check(sess, ndx)),
               families=families, records=len(lines), execution_authorized=False)
    _write_json(os.path.join(out_dir, "boos_latest.json"), out)
    return out


def pulse_section(out_dir, mnq_dates, var_sr, rolls=(), cache_dir=None):
    """THE PULSE OF ICARUS through the CL gates; recomputed only when its code, preset or tape change."""
    if not os.path.exists(pulse_track.TAPE):
        return dict(status="UNAVAILABLE", reason=f"missing {pulse_track.TAPE}")
    roll_key = json.dumps(integrity.summary(list(rolls)), sort_keys=True, default=str)
    from icarus.data import load_csv as load_bars
    tape = load_bars(pulse_track.TAPE)
    ext = _extension(cache_dir, ASSETS["MNQ"]["extension_feed"]) if cache_dir else None
    tape += extend.bars_20m(ext, tape[-1].ts) if tape else []
    roll_key += f"|{len(tape)}|{tape[-1].ts.isoformat() if tape else ''}"
    fp = hashlib.sha256((pulse_track.fingerprint() + repr(var_sr) + roll_key).encode()).hexdigest()
    cached = _read_json(os.path.join(out_dir, "pulse_latest.json"), {})
    if cached.get("fingerprint") == fp:
        return cached
    raw, moved = integrity.back_adjust_bars(tape, 20, list(rolls))
    runs = {}
    plan = [("HA_REAL_FILLS", "base"), ("CANDLES", "base"), ("HA_HA_FILLS", "base"),
            ("HA_REAL_FILLS", "stress"), ("CANDLES", "stress"), ("HA_REAL_FILLS", "repo_convention")]
    for variant, cost in plan:
        com, slip = pulse_track.COSTS[cost]
        runs[(variant, cost)] = pulse_track.run_variant(raw, variant, com, slip)
    all_dates = set(mnq_dates)
    for closed in runs.values():
        all_dates |= set(pulse_track.session_date_of([c.exit_ts for c in closed]))
    dates = sorted(all_dates)
    series, counts, stress = {}, {}, {}
    for (variant, cost), closed in runs.items():
        pnl, cnt = pulse_track.daily_pnl(closed, dates)
        if cost == "base":
            series[variant], counts[variant] = pnl, cnt
        elif cost == "stress":
            stress[variant] = pnl
    fwd_mask = (pd.to_datetime(pd.Series(dates)) >= pd.Timestamp(FORWARD_START)).to_numpy()
    rec = validate.evaluate_external(dates, series, counts, stress, ("HA_REAL_FILLS", "CANDLES"),
                                     pulse_track.PULSE_TRIALS_ASSUMED, var_sr, forward_start=FORWARD_START)
    conv = runs[("HA_REAL_FILLS", "repo_convention")]
    out = dict(schema="cl_lab.pulse/1", fingerprint=fp, strategy="THE PULSE OF ICARUS v3.1 (repo port)",
               preset=pulse_track.PRESET, preset_source="presets/NQ-20m-ultracoded.json (RECONSTRUCTED)",
               tape=pulse_track.TAPE, costs=pulse_track.COSTS, trials_assumed_for_dsr=pulse_track.PULSE_TRIALS_ASSUMED,
               var_sr_from_grammar=var_sr, variants=rec, integrity=integrity.summary(moved),
               tape_last_bar_close=(tape[-1].ts.isoformat() if tape else None),
               forward={v: dict(after=str(FORWARD_START), trades=int(counts[v][fwd_mask].sum()), net_usd=round(float(series[v][fwd_mask].sum()), 2))
                        for v in series}, repo_convention_ha_real_fills=dict(trades=len(conv), net_usd=round(sum(c.profit for c in conv), 2)),
               totals={f"{v}|{c}": dict(trades=len(cl), net_usd=round(sum(x.profit for x in cl), 2)) for (v, c), cl in runs.items()},
               execution_authorized=False)
    _write_json(os.path.join(out_dir, "pulse_latest.json"), out)
    return out


def run_cycle(out_dir, cache_dir=".cl_cache", assets=None, now=None, external_dir=".external_data_cache"):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    at = now.isoformat()
    names = assets or list(ASSETS)
    cands = grammar.enumerate_candidates()
    loaded = {n: load_asset(n, ASSETS[n], cache_dir) for n in names}
    corpus_state = corpus.inspect()
    inputs = dict(data={n: v[1] for n, v in loaded.items()}, corpus=corpus_state,
                  grammar=grammar.GRAMMAR_VERSION,
                  registration_hash=grammar.registration_hash(cands), gates=validate.GATES_VERSION,
                  thresholds=validate.T, code=_code_identity(), lab=LAB_VERSION,
                  pulse=(pulse_track.fingerprint() if "MNQ" in names else None),
                  explore=dict(version=explore.EXPLORE_VERSION, per_run=explore.EXPLORE_PER_RUN, day=now.date().isoformat()),
                  r2=hypotheses_r2.R2_VERSION, ml=ml.ML_VERSION, data_version=integrity.DATA_VERSION,
                  prereg_r2=(_sha_file(PREREG_R2) if os.path.exists(PREREG_R2) else None))
    hist = os.path.join(cache_dir, "databento_hist_nq_5m.csv.gz")
    inputs["nq_history"] = _sha_file(hist) if os.path.exists(hist) else None
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
    run_id = f"cl-lab-{fingerprint[:16]}"
    latest_path = os.path.join(out_dir, "latest.json")
    prev = _read_json(latest_path, {})
    if prev.get("input_fingerprint") == fingerprint:
        return dict(status="NO_NEW_INPUTS", run_id=run_id)

    hb_path = os.path.join(out_dir, "heartbeat.json")
    _write_json(hb_path, dict(lane=LANE, status="IN_PROGRESS", run_id=run_id, started_at=at,
                              execution_authorized=False))
    reg = _read_json(os.path.join(out_dir, "champions.json"), None)
    ledger_path = os.path.join(out_dir, "explore_ledger.jsonl")
    ledger = explore.load_ledger(ledger_path)
    per_asset, full, new_ledger = {}, {}, []

    def _forward(asset, rec, ctx):
        for e in reg["entries"].values():
            if e["asset"] == asset and e["id"] in rec:
                e["forward"] = validate.forward_stats(ctx, e["id"], max(pd.Timestamp(e["first_registered_at"]).date(),
                                                                        FORWARD_START - pd.Timedelta(days=1)))

    ndx_c, dgs = _daily_feed(cache_dir, "fred_nasdaq100", "NASDAQ100"), _daily_feed(cache_dir, "fred_dgs10", "DGS10")
    me_sigs = []
    if ndx_c is not None and dgs is not None and len(ndx_c) > 300:
        brec, bdiag, me_sigs = hypotheses_r2.month_end_daily(ndx_c, dgs, FORWARD_START)
        for v, r in brec.items():
            r.update(family="monthend", params=dict(variant=v))
        reg = registry.merge(reg, "NDX", {r["id"]: r for r in brec.values()}, run_id, at, hypotheses_r2.R2_VERSION)
        calendar_flows = dict(status="EVALUATED", version=hypotheses_r2.R2_VERSION, source="FRED NASDAQ100 + FRED DGS10",
                              diagnostics=bdiag, records=list(brec.values()), recent_signals=me_sigs[-6:])
        full["NDX"] = list(brec.values())
    else:
        calendar_flows = dict(status="UNAVAILABLE", reason="fred_nasdaq100 or fred_dgs10 not cached")
    for n in names:
        sess, ident = loaded[n]
        if sess is None:
            per_asset[n] = dict(data=ident, status="UNAVAILABLE")
            continue
        cfg = ASSETS[n]
        rec, diag, ctx = validate.evaluate(sess, cands, cfg["cost"], cfg["stress"], cfg["metric"],
                                           forward_start=FORWARD_START)
        reg = registry.merge(reg, n, rec, run_id, at, grammar.GRAMMAR_VERSION)
        for key, e in reg["entries"].items():
            if e["asset"] == n and e["id"] in rec:
                e["forward"] = validate.forward_stats(ctx, e["id"], max(pd.Timestamp(e["first_registered_at"]).date(),
                                                                         FORWARD_START - pd.Timedelta(days=1)))
        counts = pd.Series([r["status"] for r in rec.values()]).value_counts().to_dict()
        ranked = sorted(rec.values(), key=lambda r: -(r["tune_t"] if r["tune_t"] is not None else -99))
        keep = [r for r in rec.values() if r["status"] in ("CHAMPION", "CHALLENGER")]
        per_asset[n] = dict(data=ident, status="EVALUATED", sessions=int(sess.D), diagnostics=diag,
                            status_counts=counts, cost_model=cfg["cost"].spec(), stress_model=cfg["stress"].spec(),
                            champions=[r for r in keep if r["status"] == "CHAMPION"],
                            challengers=[r for r in keep if r["status"] == "CHALLENGER"],
                            top_by_tune_t=[{k: r[k] for k in ("id", "family", "params", "tune_trades", "tune_t",
                                                              "dsr", "status")} for r in ranked[:15]])
        full[n] = list(rec.values())
        prior = [r for r in ledger if r["asset"] == n]
        batch = explore.sample(n, now.date().isoformat(), {r["id"] for r in prior})
        xrec, xdiag, _ = validate.evaluate(
            sess, batch, cfg["cost"], cfg["stress"], cfg["metric"], forward_start=FORWARD_START,
            run_fn=explore.run_x, neighbour_fn=explore.neighbours,
            prior_pvals=[r["p"] for r in prior] + [r["tune_p"] for r in rec.values()],
            prior_trials=len(prior) + (diag["m_eff"] or 0), prior_hold=sum(r.get("h", 0) for r in prior))
        reg = registry.merge(reg, n, xrec, run_id, at, explore.EXPLORE_VERSION)
        new_ledger += [dict(asset=n, id=r["id"], f=r["family"], run=run_id, p=r["tune_p"], t=r["tune_t"],
                            s=r["status"][0], h=int("hold_t" in r)) for r in xrec.values()]
        xcounts = pd.Series([r["status"] for r in xrec.values()]).value_counts().to_dict()
        per_asset[n]["explorer"] = dict(version=explore.EXPLORE_VERSION, batch=len(batch), explored_before=len(prior),
                                        status_counts=xcounts, diagnostics=xdiag,
                                        promoted=[r for r in xrec.values() if r["status"] in ("CHAMPION", "CHALLENGER")],
                                        best=sorted(({k: r[k] for k in ("id", "family", "params", "tune_trades",
                                                                       "tune_t", "dsr", "status")}
                                                     for r in xrec.values()),
                                                    key=lambda r: -(r["tune_t"] if r["tune_t"] is not None else -99))[:5])
        full[n] += list(xrec.values())
        hrec, hdiag, _ = validate.evaluate(sess, hypotheses.CANDIDATES, cfg["cost"], cfg["stress"], cfg["metric"],
                                           forward_start=FORWARD_START, run_fn=hypotheses.run_r)
        reg = registry.merge(reg, n, hrec, run_id, at, hypotheses.HYPOTHESES_VERSION)
        per_asset[n]["hypotheses"] = dict(
            version=hypotheses.HYPOTHESES_VERSION, diagnostics=hdiag,
            records=[{k: r.get(k) for k in ("id", "family", "params", "tune_trades", "tune_t", "dsr", "hold_t",
                                            "hold_holm_p", "status")} for r in hrec.values()])
        full[n] += list(hrec.values())
        r2 = dict(version=hypotheses_r2.R2_VERSION)
        keep_r = ("id", "family", "params", "tune_trades", "tune_t", "dsr", "hold_trades", "hold_t", "hold_holm_p",
                  "hold_mean", "hold_mean_stress", "status")
        if n == "MNQ":
            arec, adiag, actx = hypotheses_r2.hold_confirm(sess, hypotheses_r2.A_CANDIDATES, cfg["cost"], cfg["stress"],
                                                           hypotheses_r2.run_a, FORWARD_START, cfg["metric"])
            reg = registry.merge(reg, n, arec, run_id, at, hypotheses_r2.HC_VERSION)
            _forward(n, arec, actx)
            r2["eod_reversal"] = dict(diagnostics=adiag, records=list(arec.values()))
            r2["pre_fomc"] = hypotheses_r2.event_study(sess, cfg["cost"], FORWARD_START)
            r2["month_end_mnq"] = (hypotheses_r2.month_end_twin(sess, me_sigs, cfg["cost"]) if me_sigs
                                   else dict(status="UNAVAILABLE"))
            full[n] += list(arec.values())
        else:
            drec, ddiag, dctx = validate.evaluate(sess, hypotheses_r2.D_CANDIDATES, cfg["cost"], cfg["stress"],
                                                  cfg["metric"], forward_start=FORWARD_START, run_fn=hypotheses_r2.run_d)
            reg = registry.merge(reg, n, drec, run_id, at, hypotheses_r2.R2_VERSION)
            _forward(n, drec, dctx)
            r2["flow"] = dict(available="TB" in sess.cache, diagnostics=ddiag,
                              records=[{k: r.get(k) for k in keep_r} for r in drec.values()])
            if hypotheses_r2.FORWARD_WATCH.get(n):
                r2["forward_watch"] = hypotheses_r2.forward_watch(dctx, hypotheses_r2.FORWARD_WATCH[n], FORWARD_START)
            full[n] += list(drec.values())
            hc = [c for c in hypotheses_r2.D_CANDIDATES if c.id in hypotheses_r2.R3_HOLD_CONFIRM.get(n, ())]
            if hc:  # R3-1: TUNE-selected rule decided on HOLD only (registered before its HOLD statistic existed)
                h3, h3diag, h3ctx = hypotheses_r2.hold_confirm(sess, hc, cfg["cost"], cfg["stress"], hypotheses_r2.run_d,
                                                               FORWARD_START, cfg["metric"])
                h3 = {f"{k}@hc1": dict(v, id=f"{k}@hc1", protocol="cl-hc1 (R3-1)") for k, v in h3.items()}
                h3ctx = dict(h3ctx, ids=[f"{i}@hc1" for i in h3ctx["ids"]],
                             trades={f"{k}@hc1": v for k, v in h3ctx["trades"].items()})
                reg = registry.merge(reg, n, h3, run_id, at, "cl-r3")
                _forward(n, h3, h3ctx)
                r2["hold_confirmation_r3"] = dict(diagnostics=h3diag, records=list(h3.values()))
                full[n] += list(h3.values())
        per_asset[n]["r2"] = r2
        mrec, mdiag, mctx = validate.evaluate(sess, ml.CANDIDATES, cfg["cost"], cfg["stress"], cfg["metric"],
                                              forward_start=FORWARD_START, run_fn=ml.run_m)
        reg = registry.merge(reg, n, mrec, run_id, at, ml.ML_VERSION)
        _forward(n, mrec, mctx)
        per_asset[n]["ml"] = dict(version=ml.ML_VERSION, diagnostics=mdiag,
                                  records=[{k: r.get(k) for k in keep_r} for r in mrec.values()],
                                  qualification=[ml.qualify(c, sess, cfg["cost"], cfg["metric"], FORWARD_START)
                                                 for c in ml.CANDIDATES])
        full[n] += list(mrec.values())
        if n == "MNQ":
            p = pulse_section(out_dir, list(sess.dates), diag["var_sr"], sess.cache.get("rolls", ()), cache_dir)
            per_asset[n]["pulse"] = {k: p.get(k) for k in ("strategy", "variants", "totals", "trials_assumed_for_dsr",
                                                           "preset_source", "status", "reason", "forward",
                                                           "tape_last_bar_close")}

    try:  # the backward test must never stop the forward lab from persisting its run
        boos_out = boos_section(out_dir, cache_dir, external_dir)
    except Exception as ex:  # noqa: BLE001
        boos_out = dict(status="ERROR", protocol=boos.BOOS_VERSION, error=f"{type(ex).__name__}: {ex}"[:300])
    payload = dict(schema="cl_lab.run/1", lane=LANE, run_id=run_id, input_fingerprint=fingerprint, inputs=inputs,
                   started_at=at, finished_at=pd.Timestamp.now(tz="UTC").isoformat(), code_commit=_git_commit(),
                   candidates=len(cands), assets=per_asset, corpus=corpus_state, evidence_class="RESEARCH_ONLY",
                   calendar_flows=calendar_flows,
                   backward_oos={k: v for k, v in boos_out.items() if k not in ("families",)} |
                   dict(families={f: dict(diagnostics=v["diagnostics"], confirmed=v["confirmed"])
                                  for f, v in (boos_out.get("families") or {}).items()}),
                   tune_end=str(validate.TUNE_END), forward_start=str(FORWARD_START),
                   execution_authorized=EXECUTION_AUTHORIZED, production_decision_authorized=False)
    hist_sha = _write_json(os.path.join(out_dir, "history", f"{run_id}.json"), payload)
    latest_sha = _write_json(latest_path, payload)
    if hist_sha != latest_sha:
        raise IOError("latest.json does not equal the immutable history record")
    explore.append_ledger(ledger_path, new_ledger)
    lines = [json.dumps(dict(asset=n, run_id=run_id, **r), sort_keys=True, separators=(",", ":"), default=str)
             for n in sorted(full) for r in sorted(full[n], key=lambda r: r["id"])]
    cpath = os.path.join(out_dir, "candidates_latest.jsonl")
    with open(cpath + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(cpath + ".tmp", cpath)
    _write_json(os.path.join(out_dir, "champions.json"), reg)
    feeds = _read_json(os.path.join(out_dir, "feeds_manifest.json"), {}).get("feeds", {})
    depth_corpus = {}
    for lane in ("index", "diversifier"):
        d = _read_json(os.path.join(out_dir, f"databento_depth_corpus_{lane}.json"), {})
        if d:
            per_root = {}
            for row in d.get("requests", []):
                root = row.get("root")
                if not root:
                    continue
                rec = per_root.setdefault(root, {"ok": 0, "cached": 0, "errors": 0})
                status = row.get("status")
                if status == "ok" and row.get("request_performed"):
                    rec["ok"] += 1
                elif status == "cached":
                    rec["cached"] += 1
                elif status in ("download_error", "estimate_error"):
                    rec["errors"] += 1
            depth_corpus[lane] = {
                k: d.get(k) for k in (
                    "status", "profile", "account", "budget_usd",
                    "max_request_usd", "estimated_requested_usd",
                    "downloaded_slices", "cached_slices", "raw_retention",
                    "feature_resolution", "selection_method",
                )
            }
            depth_corpus[lane]["roots"] = per_root
    external_fabric = _read_json(os.path.join(out_dir, "external_data_fabric.json"), {})
    external_summary = external_fabric.get("summary", {}) if isinstance(external_fabric, dict) else {}
    _write_json(os.path.join(out_dir, "ui_feed.json"), dict(
        schema="cl_lab.ui_feed/1", lane=LANE, run_id=run_id, generated_at=at, evidence_class="RESEARCH_ONLY",
        ui_state="RESEARCH ONLY", execution_authorized=False, production_decision_authorized=False,
        feeds={k: v.get("status") for k, v in feeds.items()},
        databento_depth_corpus=depth_corpus,
        external_data_fabric={
            "provider_status": external_summary.get("provider_status", {}),
            "universe": external_summary.get("universe", []),
            "equity_tick_pressure": external_summary.get("equity_tick_pressure", {}),
            "upcoming_focus_earnings": external_summary.get("upcoming_focus_earnings", []),
        },
        economic_events=_economic_events_ui(out_dir, now),
        corpus={k: corpus_state.get(k) for k in ("status", "dataset", "roll_rule", "minutes",
                                                 "verified_assets", "blocked_assets", "assets")},
        assets={n: {k: v.get(k) for k in ("status", "sessions", "status_counts", "diagnostics", "champions",
                                          "challengers", "pulse", "explorer", "hypotheses", "r2")}
                for n, v in per_asset.items()},
        ml={n: [{k: r.get(k) for k in ("id", "params", "tune_trades", "tune_t", "dsr", "status")}
                for r in (v.get("ml") or {}).get("records", [])] for n, v in per_asset.items()},
        calendar_flows={k: calendar_flows.get(k) for k in ("status", "version", "diagnostics", "recent_signals")} |
        dict(records=[{k: r.get(k) for k in ("id", "variant", "tune_trades", "tune_t", "dsr", "hold_t", "status")}
                      for r in calendar_flows.get("records", [])]),
        integrity=(per_asset.get("MNQ") or {}).get("data", {}).get("integrity")))
    _write_json(hb_path, dict(lane=LANE, status="IDLE", last_run_id=run_id, last_completed_at=payload["finished_at"],
                              latest_sha256=latest_sha, execution_authorized=False))
    return dict(status="RUN_PERSISTED", run_id=run_id, latest_sha256=latest_sha)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="automation_intelligence/cl_lab")
    ap.add_argument("--cache", default=".cl_cache")
    ap.add_argument("--assets", default="")
    ap.add_argument("--now", default=None)
    ap.add_argument("--external", default=".external_data_cache")
    a = ap.parse_args(argv)
    res = run_cycle(a.out, a.cache, [x for x in a.assets.split(",") if x] or None, a.now, a.external)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
