"""Exhaustive variant search over THE PULSE OF ICARUS's own 185 inputs.

Driven by `icarus_engine/strategy/pine_inputs_meta.json` -- the script's own
input declarations -- so every sampled value respects the bounds, steps and
option sets the author declared, rather than ranges invented here.

Anchored on the configuration transcribed from the ICARUS PROTO SUITE 01 screen
recording (MNQ1! 10m), because a random draw across 185 dimensions is a needle
in a haystack. Each variant perturbs a random SUBSET of fields around that
anchor, which is coordinate search around a known-good point rather than blind
sampling.

Selection discipline is the same as tools/sweep.py: screen on a short slice,
confirm on the full tuning tape, then validate on a held-out tape from a
different seed that the variant was never selected on. Only the held-out
column is reportable.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

META_PATH = Path(__file__).resolve().parent.parent / "icarus_engine" / "strategy" / "pine_inputs_meta.json"

# Transcribed from the screen recording. This is the live configuration.
VIDEO_ANCHOR: dict = {
    "tp1_pts": 140.0, "tp2_pts": 200.0, "sl_pts": 80.0,
    "rate_atr_len": 25, "rate_adx_len": 16, "rate_adx_smooth": 14,
    "rate_atr_fast": 4, "rate_atr_slow": 30, "rate_eff_len": 30,
    "tpsl_mode": "Structure-Based",
    "tp1_atr_mult": 3.0, "tp2_atr_mult": 6.0, "sl_atr_mult": 4.5,
    "struct_sl_buffer_atr": 0.5, "struct_tp2_ext_mult": 1.5,
    "use_trailing_tp2": True, "trail_atr_mult": 1.5,
    "use_cooldown": True, "cooldown_bars": 15,
    "max_daily_loss": -5000.0, "qty_contracts": 1,
    "conf_min_votes": 7,
}

# Never sample these: free-text data, or switches that change what the run MEANS
# rather than how the strategy behaves.
FROZEN = {
    "fomc_dates", "hv_open_dates", "fomc_window", "hv_open_window",
    "sess_window", "sess_entry_window", "midday_window",
    "use_session", "use_entry_window", "use_eod_flat", "use_session_bias",
    "use_hour_breach", "midday_mode", "point_value", "qty_contracts",
    "max_daily_loss",
}


def load_meta() -> list[dict]:
    return json.load(open(META_PATH, encoding="utf-8"))


def _sample_numeric(entry: dict, rng: random.Random, anchor):
    """Respect declared bounds; otherwise perturb multiplicatively around the anchor."""
    lo, hi = entry.get("minval"), entry.get("maxval")
    base = anchor if anchor is not None else entry["default"]
    if lo is not None and hi is not None:
        value = rng.uniform(lo, hi)
    else:
        scale = rng.uniform(0.4, 2.2)
        value = (base if base else entry["default"] or 1.0) * scale
        if lo is not None:
            value = max(lo, value)
        if hi is not None:
            value = min(hi, value)

    if entry["kind"] == "int":
        return int(round(value))
    step = entry.get("step")
    if step:
        value = round(value / step) * step
    return round(float(value), 4)


def sample_overrides(meta: list[dict], rng: random.Random,
                     min_fields: int = 4, max_fields: int = 22) -> dict:
    """Perturb a random subset of fields around the video anchor."""
    candidates = [e for e in meta if e["name"] not in FROZEN]
    count = rng.randint(min_fields, max_fields)
    chosen = rng.sample(candidates, min(count, len(candidates)))

    out = dict(VIDEO_ANCHOR)
    for entry in chosen:
        name, kind = entry["name"], entry["kind"]
        anchor = VIDEO_ANCHOR.get(name, entry["default"])
        if kind == "bool":
            out[name] = rng.random() < 0.5
        elif kind in ("float", "int"):
            out[name] = _sample_numeric(entry, rng, anchor)
        elif kind in ("string", "timeframe"):
            options = entry.get("options")
            if options:
                out[name] = rng.choice(options)
        # sessions stay frozen -- they change what the run means, not how it behaves
    return out


@dataclass(slots=True)
class PulseVariant:
    timeframe: str
    overrides: dict = field(default_factory=dict)

    def key(self) -> str:
        return json.dumps({"tf": self.timeframe, **self.overrides}, sort_keys=True, default=str)

    def changed_from_anchor(self) -> dict:
        return {k: v for k, v in self.overrides.items()
                if k not in VIDEO_ANCHOR or VIDEO_ANCHOR[k] != v}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

import multiprocessing as mp          # noqa: E402
import statistics as st               # noqa: E402

from tools.htf_context import ContextProvider   # noqa: E402
from tools.validate_pulse import run_pulse      # noqa: E402

TAPES: dict[tuple[str, str], list] = {}
CONTEXTS: dict[tuple[str, str], ContextProvider] = {}


def evaluate(variant: PulseVariant, tape_key: str) -> dict:
    tape = TAPES[(tape_key, variant.timeframe)]
    ctx = CONTEXTS.get((tape_key, variant.timeframe))
    minutes = int(variant.timeframe.rstrip("m"))
    overrides = dict(variant.overrides)
    mode = overrides.pop("tpsl_mode", "Structure-Based")
    result = run_pulse(tape, tf_minutes=minutes, tpsl_mode=mode,
                       context=ctx, **overrides)
    if result["trades"]:
        days = max((tape[-1].ts - tape[0].ts).total_seconds() / 86400.0, 1e-9)
        result["trades_per_day"] = result["trades"] / days
    else:
        result["trades_per_day"] = 0.0
    return result


def _worker(payload):
    variant, tape_key = payload
    try:
        return variant, evaluate(variant, tape_key)
    except Exception as exc:                      # one bad draw must not kill the sweep
        return variant, {"error": f"{type(exc).__name__}: {exc}", "trades": 0}


def run_stage(variants, tape_key: str, workers: int):
    with mp.Pool(workers) as pool:
        return pool.map(_worker, [(v, tape_key) for v in variants], chunksize=1)


def passes(res: dict, *, min_trades: int, min_exp: float,
           min_tpd: float, max_tpd: float, min_win: float) -> bool:
    if "error" in res or res.get("trades", 0) < min_trades:
        return False
    return (res["expectancy"] >= min_exp
            and min_tpd <= res["trades_per_day"] <= max_tpd
            and res["win_rate"] >= min_win)


def fmt(v: PulseVariant, r: dict) -> str:
    return (f"{v.timeframe:>4s} n={r['trades']:4d} tpd={r['trades_per_day']:5.2f} "
            f"win={r['win_rate']:5.1f}% exp=${r['expectancy']:+9,.0f} "
            f"hold={r.get('mean_bars', 0):5.1f} net=${r['net']:+11,.0f}")
