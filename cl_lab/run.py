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

from . import (EXECUTION_AUTHORIZED, LAB_VERSION, LANE, bars, costs, explore, grammar, hypotheses, pulse_track, registry,
               sessions, store, validate)

ASSETS = {
    "MNQ": dict(kind="csv", path="data/mnq_5m_full.csv", cost=costs.MNQ, stress=costs.MNQ_STRESS,
                metric="points", weekdays_only=False),
    "BTCUSDT": dict(kind="cache", feed="btcusdt_5m", cost=costs.CRYPTO_PERP, stress=costs.CRYPTO_PERP_STRESS,
                    metric="returns", weekdays_only=True),
    "ETHUSDT": dict(kind="cache", feed="ethusdt_5m", cost=costs.CRYPTO_PERP, stress=costs.CRYPTO_PERP_STRESS,
                    metric="returns", weekdays_only=True),
}
FORWARD_START = date(2026, 10, 5)  # first CL registration; sessions on/after this date are never tuned on


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


def load_asset(name, cfg, cache_dir):
    if cfg["kind"] == "csv":
        if not os.path.exists(cfg["path"]):
            return None, dict(status="UNAVAILABLE", reason=f"missing {cfg['path']}")
        df = bars.load_csv(cfg["path"])
        ident = dict(status="OK", source=cfg["path"], sha256=_sha_file(cfg["path"]))
    else:
        path = os.path.join(cache_dir, f"{cfg['feed']}.csv.gz")
        df = store.load_frame(path) if os.path.exists(path) else pd.DataFrame()
        if df.empty:
            return None, dict(status="UNAVAILABLE", reason=f"no cached feed {cfg['feed']}")
        df = df[list(bars.COLUMNS)].astype(float)
        ident = dict(status="OK", source=f"cache:{cfg['feed']}", sha256=store.sha256_frame(df))
    ident.update(rows=int(len(df)), first=df.index[0].isoformat(), last=df.index[-1].isoformat())
    adf = bars.annotate(df)
    if cfg["weekdays_only"]:
        adf = adf[pd.to_datetime(adf["session_date"]).dt.dayofweek < 5]
    sess = sessions.build_sessions(adf)
    for feed, col in (("cboe_vix", "VIX_close"), ("cboe_vix9d", "VIX9D_close")):  # causal day conditioners
        p = os.path.join(cache_dir, f"{feed}.csv.gz")
        if os.path.exists(p):
            ext = store.load_frame(p, intraday=False)
            if col in ext:
                sess.cache[("ext", col)] = ext[col]
    return sess, ident


def pulse_section(out_dir, mnq_dates, var_sr):
    """THE PULSE OF ICARUS through the CL gates; recomputed only when its code, preset or tape change."""
    if not os.path.exists(pulse_track.TAPE):
        return dict(status="UNAVAILABLE", reason=f"missing {pulse_track.TAPE}")
    fp = hashlib.sha256((pulse_track.fingerprint() + repr(var_sr)).encode()).hexdigest()
    cached = _read_json(os.path.join(out_dir, "pulse_latest.json"), {})
    if cached.get("fingerprint") == fp:
        return cached
    from icarus.data import load_csv as load_bars
    raw = load_bars(pulse_track.TAPE)
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
    rec = validate.evaluate_external(dates, series, counts, stress, ("HA_REAL_FILLS", "CANDLES"),
                                     pulse_track.PULSE_TRIALS_ASSUMED, var_sr, forward_start=FORWARD_START)
    conv = runs[("HA_REAL_FILLS", "repo_convention")]
    out = dict(schema="cl_lab.pulse/1", fingerprint=fp, strategy="THE PULSE OF ICARUS v3.1 (repo port)",
               preset=pulse_track.PRESET, preset_source="presets/NQ-20m-ultracoded.json (RECONSTRUCTED)",
               tape=pulse_track.TAPE, costs=pulse_track.COSTS, trials_assumed_for_dsr=pulse_track.PULSE_TRIALS_ASSUMED,
               var_sr_from_grammar=var_sr, variants=rec, repo_convention_ha_real_fills=dict(trades=len(conv), net_usd=round(sum(c.profit for c in conv), 2)),
               totals={f"{v}|{c}": dict(trades=len(cl), net_usd=round(sum(x.profit for x in cl), 2)) for (v, c), cl in runs.items()},
               execution_authorized=False)
    _write_json(os.path.join(out_dir, "pulse_latest.json"), out)
    return out


def run_cycle(out_dir, cache_dir=".cl_cache", assets=None, now=None):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    at = now.isoformat()
    names = assets or list(ASSETS)
    cands = grammar.enumerate_candidates()
    loaded = {n: load_asset(n, ASSETS[n], cache_dir) for n in names}
    inputs = dict(data={n: v[1] for n, v in loaded.items()}, grammar=grammar.GRAMMAR_VERSION,
                  registration_hash=grammar.registration_hash(cands), gates=validate.GATES_VERSION,
                  thresholds=validate.T, code=_code_identity(), lab=LAB_VERSION,
                  pulse=(pulse_track.fingerprint() if "MNQ" in names else None),
                  explore=dict(version=explore.EXPLORE_VERSION, per_run=explore.EXPLORE_PER_RUN, day=now.date().isoformat()))
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
        if n == "MNQ":
            p = pulse_section(out_dir, list(sess.dates), diag["var_sr"])
            per_asset[n]["pulse"] = {k: p.get(k) for k in ("strategy", "variants", "totals", "trials_assumed_for_dsr",
                                                           "preset_source", "status", "reason")}

    payload = dict(schema="cl_lab.run/1", lane=LANE, run_id=run_id, input_fingerprint=fingerprint, inputs=inputs,
                   started_at=at, finished_at=pd.Timestamp.now(tz="UTC").isoformat(), code_commit=_git_commit(),
                   candidates=len(cands), assets=per_asset, evidence_class="RESEARCH_ONLY",
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
    _write_json(os.path.join(out_dir, "ui_feed.json"), dict(
        schema="cl_lab.ui_feed/1", lane=LANE, run_id=run_id, generated_at=at, evidence_class="RESEARCH_ONLY",
        ui_state="RESEARCH ONLY", execution_authorized=False, production_decision_authorized=False,
        feeds={k: v.get("status") for k, v in feeds.items()},
        assets={n: {k: v.get(k) for k in ("status", "sessions", "status_counts", "diagnostics", "champions",
                                          "challengers", "pulse", "explorer", "hypotheses")}
                for n, v in per_asset.items()}))
    _write_json(hb_path, dict(lane=LANE, status="IDLE", last_run_id=run_id, last_completed_at=payload["finished_at"],
                              latest_sha256=latest_sha, execution_authorized=False))
    return dict(status="RUN_PERSISTED", run_id=run_id, latest_sha256=latest_sha)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="automation_intelligence/cl_lab")
    ap.add_argument("--cache", default=".cl_cache")
    ap.add_argument("--assets", default="")
    ap.add_argument("--now", default=None)
    a = ap.parse_args(argv)
    res = run_cycle(a.out, a.cache, [x for x in a.assets.split(",") if x] or None, a.now)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
