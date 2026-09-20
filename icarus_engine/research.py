"""Bounded, reproducible research. Results are candidates, never execution instructions.

Selection uses train/validation only. A persistent ledger prevents reusing a
holdout interval for the same asset, even across dataset revisions. No broker or input-file writes.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import sqlite3
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Callable, Mapping, Sequence

from .runtime import validate_values
from .strategy.inputs import Inputs


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _integer(value, name, lo=0, hi=2**53 - 1):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer between {lo} and {hi}")
    return value


def _number(value, name, lo=0.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < lo:
        raise ValueError(f"{name} must be a finite number >= {lo}")
    return value


@dataclass(frozen=True)
class Windows:
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    holdout_start: int
    holdout_end: int

    def __post_init__(self):
        values = list(asdict(self).values())
        for name, value in asdict(self).items():
            _integer(value, name)
        if any(a >= b for a, b in zip(values, values[1:])):
            raise ValueError("research windows must be strictly ordered and disjoint")


@dataclass(frozen=True)
class Policy:
    max_trials: int = 32
    max_seconds: float = 120.0
    min_entries: int = 30
    max_drawdown_pct: float = 20.0
    min_net_improvement_pct: float = 1.0
    min_expectancy_improvement_pct: float = 5.0
    min_expectancy_improvement: float = 0.0
    max_drawdown_increase_pct: float = 0.0
    stress_commission_multiplier: float = 1.5
    stress_slippage_ticks: int = 1
    require_stress: bool = True

    def __post_init__(self):
        _integer(self.max_trials, "max_trials", 1, 1000)
        _integer(self.min_entries, "min_entries", 1, 1000000)
        _number(self.max_seconds, "max_seconds", 0.01)
        _number(self.max_drawdown_pct, "max_drawdown_pct", 0.01)
        for name in ("min_net_improvement_pct", "min_expectancy_improvement_pct",
                     "min_expectancy_improvement", "max_drawdown_increase_pct"):
            _number(getattr(self, name), name)
        _number(self.stress_commission_multiplier, "stress_commission_multiplier", 1.0)
        _integer(self.stress_slippage_ticks, "stress_slippage_ticks", 1, 1000)
        if type(self.require_stress) is not bool:
            raise ValueError("require_stress must be a boolean")
        if (self.min_net_improvement_pct > 100 or self.min_expectancy_improvement_pct > 1000
                or self.max_drawdown_increase_pct > 100 or self.stress_commission_multiplier > 10):
            raise ValueError("research improvement/stress limit exceeds supported range")
        if self.max_seconds > 86400 or self.max_drawdown_pct > 100:
            raise ValueError("research duration/drawdown limit exceeds supported range")


def wilson(wins: int, total: int):
    """Descriptive 95% interval; correlated trades violate binomial independence."""
    _integer(total, "total")
    _integer(wins, "wins", 0, total)
    if total == 0:
        return None
    z = 1.959963984540054
    p = wins / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total**2)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def entry_metrics(result: Mapping):
    """Combine exit pieces; omit an entry with any still-open residue.

    Engine rows identify entries by direction, timestamp, signal and price.
    Same-price pyramids sharing all four are conservatively treated as a single
    entry cohort, not invented independent observations.
    """
    cfg = result.get("config", {})
    if cfg.get("fill_on") != "real":
        raise ValueError("research requires real-price fills")
    capital = _number(cfg.get("capital"), "capital", 0.01)
    _number(cfg.get("commission"), "commission")
    _integer(cfg.get("slippage_ticks"), "slippage_ticks")
    groups = {}
    account_net = 0.0
    for row in result.get("trades", []):
        key = (row["type"], row["entry_ts"], row["entry_signal"], row["entry_px"])
        g = groups.setdefault(key, {"pnl": 0.0, "open": False, "exit": 0})
        pnl = row["pnl"]
        if isinstance(pnl, bool) or not isinstance(pnl, (int, float)) or not math.isfinite(pnl):
            raise ValueError("trade pnl must be finite")
        g["pnl"] += pnl
        account_net += pnl
        g["open"] |= bool(row["open"])
        g["exit"] = max(g["exit"], row.get("exit_ts") or 0)
    closed = sorted((g for g in groups.values() if not g["open"]), key=lambda g: g["exit"])
    pnls = [g["pnl"] for g in closed]
    wins = sum(p > 0 for p in pnls)
    net = sum(pnls)
    drawdown = result.get("summary", {}).get("max_drawdown", {}).get("all")
    _number(drawdown, "max_drawdown")
    # The per-bar curve includes unrealized losses and residual open positions.
    peak, mtm_dd = capital, 0.0
    for _, eq in result.get("equity", []):
        if isinstance(eq, bool) or not isinstance(eq, (int, float)) or not math.isfinite(eq):
            raise ValueError("equity must be finite")
        peak = max(peak, eq)
        mtm_dd = max(mtm_dd, (peak - eq) / peak * 100)
    return {"entries": len(pnls), "open_entry_cohorts": sum(g["open"] for g in groups.values()),
            "wins": wins, "win_rate": wins / len(pnls) if pnls else None,
            "win_rate_wilson_95": wilson(wins, len(pnls)), "net_after_costs": net,
            "account_net_after_costs": account_net,
            "expectancy_after_costs": statistics.mean(pnls) if pnls else None,
            "max_drawdown_pct": max(drawdown / capital * 100, mtm_dd),
            "historical_scale_asof_valid": cfg.get("historical_scale_asof_valid") is True,
            "fill_on": "real", "capital": capital,
            "commission": cfg["commission"], "slippage_ticks": cfg["slippage_ticks"]}


def _eligible(metrics, policy):
    return (metrics["entries"] >= policy.min_entries and metrics["net_after_costs"] > 0
            and metrics["account_net_after_costs"] > 0
            and metrics["expectancy_after_costs"] > 0
            and metrics["max_drawdown_pct"] <= policy.max_drawdown_pct)


def _paired_comparison(baseline, candidate, policy):
    """Economic hurdles, not a statistical significance or accuracy claim."""
    net_delta = candidate["net_after_costs"] - baseline["net_after_costs"]
    account_delta = candidate["account_net_after_costs"] - baseline["account_net_after_costs"]
    base_expectancy = baseline["expectancy_after_costs"] or 0.0
    expectancy_delta = ((candidate["expectancy_after_costs"] or 0.0) - base_expectancy)
    net_required = baseline["capital"] * policy.min_net_improvement_pct / 100
    expectancy_required = max(policy.min_expectancy_improvement,
                              abs(base_expectancy) * policy.min_expectancy_improvement_pct / 100)
    drawdown_delta = candidate["max_drawdown_pct"] - baseline["max_drawdown_pct"]
    reasons = []
    if not _eligible(candidate, policy):
        reasons.append("candidate fails sample, positive after-cost return, or drawdown limits")
    if net_delta <= 0 or net_delta < net_required:
        reasons.append("closed-entry net improvement is below the required positive hurdle")
    if account_delta <= 0 or account_delta < net_required:
        reasons.append("account net improvement is below the required positive hurdle")
    if expectancy_delta <= 0 or expectancy_delta < expectancy_required:
        reasons.append("expectancy improvement is below the required positive hurdle")
    if drawdown_delta > policy.max_drawdown_increase_pct:
        reasons.append("drawdown deterioration exceeds policy")
    return {"passed": not reasons, "reasons": reasons, "net_after_costs_delta": net_delta,
            "account_net_after_costs_delta": account_delta, "net_improvement_required": net_required,
            "net_improvement_pct": net_delta / baseline["capital"] * 100,
            "expectancy_after_costs_delta": expectancy_delta, "expectancy_improvement_required": expectancy_required,
            "baseline_expectancy_missing": baseline["expectancy_after_costs"] is None,
            "max_drawdown_pct_delta": drawdown_delta}


def _replay_evidence(result, asset, start, end, patch, baseline_hash):
    """Retain auditable result/config hashes; refuse unpaired or unproven replays."""
    cfg = result.get("config", {})
    if (result.get("asset") != asset or cfg.get("window_start") != start
            or cfg.get("window_end") != end or cfg.get("overrides") != patch):
        raise ValueError("replay asset/window/input provenance mismatch")
    rep = cfg.get("reproducibility", {})
    for name in ("source_config", "effective_config"):
        snapshot = rep.get(name)
        if not isinstance(snapshot, dict) or rep.get(name + "_sha256") != digest(snapshot):
            raise ValueError(f"replay {name} evidence is missing or mismatched")
    for name in ("subbars_sha256", "deep_sha256"):
        value = rep.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("replay data hash evidence is missing")
    source = rep["source_config"]
    try:
        fingerprint = {"spec": source["spec"], "base_inputs": source["base_inputs"],
                       "replay_config": source["runner_config"], "pts_scale": source["pts_scale"],
                       "mintick": source["mintick"]}
    except KeyError as ex:
        raise ValueError("replay baseline evidence is incomplete") from ex
    if digest(fingerprint) != baseline_hash:
        raise ValueError("replay baseline fingerprint mismatch")
    effective = rep["effective_config"]
    if effective.get("base_inputs") != {**source["base_inputs"], **patch}:
        raise ValueError("replay applied inputs differ from the requested baseline patch")
    for name in ("window_start", "window_end", "pts_scale", "leverage"):
        if name not in cfg or effective.get(name) != cfg[name]:
            raise ValueError("replay effective configuration mismatch")
    return {"result_sha256": digest(result), "config": json.loads(json.dumps(cfg, allow_nan=False)),
            "source_config_sha256": rep["source_config_sha256"],
            "subbars_sha256": rep["subbars_sha256"], "deep_sha256": rep["deep_sha256"]}


def _same_source(left, right):
    if any(left[key] != right[key] for key in ("source_config_sha256", "subbars_sha256", "deep_sha256")):
        raise ValueError("paired replay source/data provenance mismatch")


def _same_conditions(left, right, *, costs=None):
    _same_source(left, right)
    fields = ("fill_on", "chart_type", "capital", "commission", "slippage_ticks", "session", "tf",
              "point_value", "leverage", "window_start", "window_end", "pts_scale")
    for name in fields:
        expected = costs[name] if costs and name in costs else left["config"].get(name)
        if expected is None or right["config"].get(name) != expected:
            raise ValueError(f"paired replay condition mismatch: {name}")


def _grid(grid):
    if not isinstance(grid, dict) or not 1 <= len(grid) <= len(Inputs().to_dict()):
        raise ValueError("grid must name one or more strategy inputs")
    names = sorted(grid)
    known = Inputs().to_dict()
    for name in names:
        vals = grid[name]
        if name not in known or not isinstance(vals, list) or not 1 <= len(vals) <= 100:
            raise ValueError(f"invalid candidate list for {name}")
        for value in vals:
            validate_values({name: value})
        if len({digest(v) for v in vals}) != len(vals):
            raise ValueError(f"duplicate candidate values for {name}")
    total = math.prod(len(grid[name]) for name in names)
    return names, total


def _claim_holdout(path, asset, dataset_hash, windows, study_hash):
    if path == ":memory:":
        raise ValueError("holdout consumption requires a persistent ledger")
    db = sqlite3.connect(str(path), timeout=10)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS holdouts (asset TEXT, dataset TEXT, start INTEGER, end INTEGER, study TEXT, claimed REAL)")
        db.execute("CREATE TABLE IF NOT EXISTS revealed (asset TEXT PRIMARY KEY, until_ts INTEGER NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        # Overlapping intervals count as reuse, even if their endpoints differ.
        # Appending or revising data cannot make an observed interval unseen.
        # The hash remains evidence, never a fresh-holdout authorization key.
        exists = db.execute("SELECT 1 FROM holdouts WHERE asset=? AND start<=? AND end>=?",
                            (asset, windows.holdout_end, windows.holdout_start)).fetchone()
        if exists:
            raise ValueError("holdout already consumed for this asset; obtain a new unseen interval")
        previous = db.execute("SELECT until_ts FROM revealed WHERE asset=?", (asset,)).fetchone()
        old_holdout = db.execute("SELECT MAX(end) FROM holdouts WHERE asset=?", (asset,)).fetchone()[0]
        revealed = max(previous[0] if previous else -1, old_holdout if old_holdout is not None else -1)
        if windows.holdout_start <= revealed:
            raise ValueError("holdout overlaps previously evaluated history; use a later unseen interval")
        db.execute("INSERT INTO holdouts VALUES (?,?,?,?,?,?)", (asset, dataset_hash, windows.holdout_start,
                   windows.holdout_end, study_hash, time.time()))
        db.execute("INSERT INTO revealed VALUES (?,?) ON CONFLICT(asset) DO UPDATE SET until_ts=MAX(until_ts,excluded.until_ts)",
                   (asset, windows.holdout_end))
        db.commit()
    finally:
        db.close()


def _reveal_history(path, asset, until_ts):
    """Replay initialization reads prior history too, so advance a watermark."""
    if path == ":memory:":
        raise ValueError("research requires a persistent evidence ledger")
    db = sqlite3.connect(str(path), timeout=10)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS revealed (asset TEXT PRIMARY KEY, until_ts INTEGER NOT NULL)")
        db.execute("INSERT INTO revealed VALUES (?,?) ON CONFLICT(asset) DO UPDATE SET until_ts=MAX(until_ts,excluded.until_ts)",
                   (asset, until_ts))
        db.commit()
    finally:
        db.close()


def run_search(asset: str, grid: dict, windows: Windows, evaluate: Callable,
               *, dataset_hash: str, baseline_hash: str, holdout_ledger: str,
               policy: Policy = Policy(), checkpoint: Callable | None = None, cancelled: Callable | None = None,
               stress_evaluate: Callable | None = None):
    """evaluate(patch, start, end) must use one frozen source for every call.

    stress_evaluate(patch, start, end, commission=..., slippage_ticks=...)
    must replay that same frozen source. Economic hurdles are preregistered in
    the manifest; a single claimed holdout batch tests only the selected patch
    and baseline at normal and stressed costs. A cancelled partial batch remains
    consumed. Deadlines are cooperative between replay calls.
    """
    if not isinstance(asset, str) or not asset or len(asset) > 32:
        raise ValueError("asset required")
    for value in (dataset_hash, baseline_hash):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("dataset/baseline hashes must be SHA-256 hex")
    names, total = _grid(grid)
    manifest = {"asset": asset, "grid": grid, "windows": asdict(windows), "policy": asdict(policy),
                "dataset_hash": dataset_hash, "baseline_hash": baseline_hash, "version": 2,
                "selection_rule": "maximum validation account-net improvement; then lower drawdown; then train improvement",
                "holdout_rule": "one claimed baseline/selected batch at preregistered normal and stress costs"}
    study_hash = digest(manifest)
    out = {"manifest": manifest, "study_hash": study_hash, "status": "running", "total_combinations": total,
           "trials": [], "selected": None, "holdout": None, "research_qualified": False,
           "baseline": {}, "baseline_evidence": {}, "holdout_evidence": None, "holdout_comparison": None,
           "selection": None, "holdout_consumed": False, "qualification_reasons": [],
           "stress": {"status": "enabled" if policy.require_stress and stress_evaluate else
                      "disabled" if not policy.require_stress else "unavailable",
                      "costs": None, "baseline": {}, "baseline_evidence": {},
                      "holdout": None, "holdout_evidence": None, "holdout_comparison": None},
           "execution_authorized": False, "accuracy_guaranteed": False,
           "limitations": ["Entry cohorts and market regimes are not independent binomial trials.",
                           "Selection over many variants can overfit; this is one holdout, not a profitability certificate.",
                           "Improvement hurdles are configured economic thresholds, not statistical significance or an accuracy guarantee."]}
    started = time.monotonic()
    budget_end = started + policy.max_seconds
    stopped = lambda: (cancelled and cancelled()) or time.monotonic() >= budget_end
    bounds = {name: (getattr(windows, name + "_start"), getattr(windows, name + "_end"))
              for name in ("train", "validation", "holdout")}
    anchor = None

    def publish():
        if checkpoint:
            checkpoint(json.loads(json.dumps(out, allow_nan=False)))

    def finish(status):
        out["status"] = status
        out["elapsed_seconds"] = time.monotonic() - started
        publish()
        return out

    def interrupted():
        return finish("cancelled" if cancelled and cancelled() else "time_limit")

    def replay(patch, split, *, stress=False):
        nonlocal anchor
        start, end = bounds[split]
        if split != "holdout":
            _reveal_history(holdout_ledger, asset, end)
        costs = out["stress"]["costs"] if stress else {}
        result = (stress_evaluate(patch, start, end, **costs) if stress else evaluate(patch, start, end))
        metrics = entry_metrics(result)
        evidence = _replay_evidence(result, asset, start, end, patch, baseline_hash)
        if anchor is None:
            anchor = evidence
        _same_conditions(anchor, evidence, costs={"window_start": start, "window_end": end, **costs})
        return metrics, evidence

    # Baselines are replayed once per window/scenario and reused for all trials.
    for split in ("train", "validation"):
        if stopped():
            return interrupted()
        out["baseline"][split], out["baseline_evidence"][split] = replay({}, split)
    if out["stress"]["status"] == "enabled":
        out["stress"]["costs"] = {
            "commission": out["baseline"]["train"]["commission"] * policy.stress_commission_multiplier,
            "slippage_ticks": out["baseline"]["train"]["slippage_ticks"] + policy.stress_slippage_ticks}
        for split in ("train", "validation"):
            if stopped():
                return interrupted()
            out["stress"]["baseline"][split], out["stress"]["baseline_evidence"][split] = replay({}, split, stress=True)
    publish()
    for values in itertools.islice(itertools.product(*(grid[n] for n in names)), policy.max_trials):
        if stopped():
            break
        patch = dict(zip(names, values))
        train, train_evidence = replay(patch, "train")
        if stopped():
            break
        validation, validation_evidence = replay(patch, "validation")
        comparisons = {split: _paired_comparison(out["baseline"][split], metrics, policy)
                       for split, metrics in (("train", train), ("validation", validation))}
        trial = {"inputs": patch, "train": train, "validation": validation,
                 "result_evidence": {"train": train_evidence, "validation": validation_evidence},
                 "paired_comparison": comparisons, "stress": {},
                 "eligible": all(c["passed"] for c in comparisons.values())}
        if trial["eligible"] and out["stress"]["status"] == "enabled":
            for split in ("train", "validation"):
                if stopped():
                    return interrupted()
                metrics, evidence = replay(patch, split, stress=True)
                comparison = _paired_comparison(out["stress"]["baseline"][split], metrics, policy)
                trial["stress"][split] = {"metrics": metrics, "result_evidence": evidence,
                                           "paired_comparison": comparison}
                trial["eligible"] &= comparison["passed"]
        out["trials"].append(trial)
        publish()
    if stopped():
        return interrupted()
    candidates = [t for t in out["trials"] if t["eligible"]]
    out["search_truncated"] = len(out["trials"]) < total
    if not candidates:
        return finish("no_candidate")
    selected = max(candidates, key=lambda t: (t["paired_comparison"]["validation"]["account_net_after_costs_delta"],
                                             -t["validation"]["max_drawdown_pct"],
                                             t["paired_comparison"]["train"]["account_net_after_costs_delta"]))
    out["selected"] = selected["inputs"]
    selection = {"study_hash": study_hash, "inputs": out["selected"], "policy": asdict(policy),
                 "validation_result_sha256": selected["result_evidence"]["validation"]["result_sha256"],
                 "baseline_validation_result_sha256": out["baseline_evidence"]["validation"]["result_sha256"],
                 "stress_costs": out["stress"]["costs"]}
    out["selection"] = {**selection, "selection_sha256": digest(selection)}
    publish()  # Persist the exact choice before any holdout observation.
    if stopped():
        return interrupted()
    _claim_holdout(holdout_ledger, asset, dataset_hash, windows, study_hash)
    out["holdout_consumed"] = True
    publish()
    if stopped():
        return interrupted()
    out["baseline"]["holdout"], out["baseline_evidence"]["holdout"] = replay({}, "holdout")
    if stopped():
        return interrupted()
    holdout, out["holdout_evidence"] = replay(selected["inputs"], "holdout")
    out["holdout"] = holdout
    out["holdout_comparison"] = _paired_comparison(out["baseline"]["holdout"], holdout, policy)
    if not out["holdout_comparison"]["passed"]:
        out["qualification_reasons"].append("normal-cost holdout failed paired improvement hurdles")
    # This fixed batch is declared before observing any holdout result. Its outcome
    # cannot change the selected patch or authorize another look at the interval.
    if out["stress"]["status"] == "enabled":
        if stopped():
            return interrupted()
        out["stress"]["baseline"]["holdout"], out["stress"]["baseline_evidence"]["holdout"] = replay({}, "holdout", stress=True)
        if stopped():
            return interrupted()
        stressed, evidence = replay(selected["inputs"], "holdout", stress=True)
        comparison = _paired_comparison(out["stress"]["baseline"]["holdout"], stressed, policy)
        out["stress"].update(holdout=stressed, holdout_evidence=evidence, holdout_comparison=comparison)
        if not comparison["passed"]:
            out["qualification_reasons"].append("stress-cost holdout failed paired improvement hurdles")
    else:
        out["qualification_reasons"].append("stress-cost comparison is " + out["stress"]["status"])
    all_metrics = [*out["baseline"].values(), selected["train"], selected["validation"], holdout,
                   *out["stress"]["baseline"].values(), *(item["metrics"] for item in selected["stress"].values())]
    if out["stress"]["holdout"] is not None:
        all_metrics.append(out["stress"]["holdout"])
    if not all(metrics["historical_scale_asof_valid"] for metrics in all_metrics):
        out["qualification_reasons"].append("historical scale lacks valid as-of provenance")
    if stopped():
        return interrupted()
    out["research_qualified"] = not out["qualification_reasons"]
    return finish("complete")


def return_correlation(left: Sequence[tuple], right: Sequence[tuple], *, as_of: int, min_pairs=20):
    """Pearson correlation of simple returns over identical observed intervals.

    Rows are (observation_at, received_at, close). Missing bars are not filled;
    intervals must match at both ends. Feed/instrument identity belongs to the
    caller's evidence. This estimates association, not causality or lead time.
    """
    _integer(as_of, "as_of")
    _integer(min_pairs, "min_pairs", 2)
    def returns(rows):
        points = {}
        for observed, received, price in rows:
            _integer(observed, "observation_at")
            _integer(received, "received_at")
            _number(price, "close", 0.000000000001)
            if received < observed:
                raise ValueError("receipt precedes observation")
            if observed <= as_of and received <= as_of:
                if observed in points:
                    raise ValueError("duplicate observation; select a point-in-time revision first")
                points[observed] = price
        times = sorted(points)
        return {(a, b): points[b] / points[a] - 1 for a, b in zip(times, times[1:])}
    l, r = returns(left), returns(right)
    shared = sorted(l.keys() & r.keys())
    if len(shared) < min_pairs:
        return {"pairs": len(shared), "correlation": None, "reason": "insufficient aligned returns"}
    x, y = [l[k] for k in shared], [r[k] for k in shared]
    mx, my = statistics.mean(x), statistics.mean(y)
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - mx)**2 for a in x) * sum((b - my)**2 for b in y))
    return {"pairs": len(shared), "correlation": max(-1.0, min(1.0, numerator / denominator)) if denominator else None,
            "reason": None if denominator else "constant returns", "as_of": as_of}
