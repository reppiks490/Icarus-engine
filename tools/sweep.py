"""Exhaustive variant search with held-out validation and selection correction.

Three stages, and the discipline is the point:

  1. **Screen** a large random sample of the parameter space on a SHORT slice of
     the tuning tape. Cheap, throws away the obvious failures.
  2. **Confirm** the screen's survivors on the FULL tuning tape.
  3. **Validate** those survivors on a HELD-OUT tape they were never selected
     on, generated from a different seed.

Only stage-3 numbers are reportable. Stage-1 and stage-2 numbers are selection
artefacts by construction: search 800 variants and the best 20 on the tuning
tape are the 20 that best fit that tape's noise. That is methodology trap 4 in
docs/RESEARCH_LOG.md and it is the single most common way a backtest lies.

The expected number of variants that clear any tuning-tape bar by luck alone is
reported alongside the survivors, so the reader can see how much of the result
the search itself manufactured.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import random
import statistics as st
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icarus.config import AssetClass, ConfluenceWeights, profile_for
from icarus.data import synthetic_for
from icarus.exits import HybridExit, HybridParams
from icarus.indicators import clamp
from icarus.strategy import IcarusEngine
from icarus.timeframe import resample
import icarus.signal as signal_module

_ORIGINAL_LOCATION = signal_module.ConfluenceEngine._location_score


# ---------------------------------------------------------------------------
# Location premise variants (N-001)
# ---------------------------------------------------------------------------

def _invert(direction, price, vwap):
    return 1.0 - _ORIGINAL_LOCATION(direction, price, vwap)


def _continuation(direction, price, vwap):
    """Displacement in the trade's direction confirms; over-extension rolls off."""
    dev = vwap.deviation(price)
    if dev == 0.0 and vwap.value is None:
        return 0.5
    confirm = direction * dev
    if confirm <= 0.0:
        return clamp(0.5 + 0.18 * confirm)
    return clamp(0.5 + 0.5 * min(confirm, 2.0) / 2.0 - 0.22 * max(0.0, confirm - 3.0))


# The full intraday band. 1m is excluded: at MNQ friction the edge-to-cost
# ratio gate rejects nearly every 1m bar, so it only burns compute.
TIMEFRAME_CHOICES = ("2m", "3m", "5m", "10m", "15m", "30m")

LOCATION_MODES = {
    "normal": _ORIGINAL_LOCATION,
    "invert": _invert,
    "continuation": _continuation,
}


# ---------------------------------------------------------------------------
# Search space
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Variant:
    timeframe: str
    location_mode: str
    # confluence
    w_location: float
    w_order_flow: float
    w_structure: float
    w_momentum: float
    w_volatility: float
    w_sweep_quality: float
    min_confluence: float
    min_target_room_atr: float
    # gates
    min_atr_pct: float
    max_atr_pct: float
    sweep_min_pen: float
    sweep_max_pen: float
    sweep_reclaim: int
    # exit
    min_stop_atr: float
    max_stop_atr: float
    first_target_r: float
    scale_out: float
    trail_atr: float
    kalman_buf: float
    endurance_min_r: float
    breakeven_arm_r: float
    time_stop_bars: int
    cooldown_bars: int

    def key(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def sample_variant(rng: random.Random) -> Variant:
    return Variant(
        # Uniform across the whole intraday band. An earlier version weighted
        # 2m/5m at 80% on the reasoning that slower bars gave thin samples --
        # but that is a tape-length problem, not a timeframe problem, and the
        # system is built to hold long intraday trends, which lives UP here.
        timeframe=rng.choice(TIMEFRAME_CHOICES),
        location_mode=rng.choice(["invert", "continuation", "normal"]),
        w_location=round(rng.uniform(0.0, 1.30), 2),
        w_order_flow=round(rng.uniform(0.30, 1.40), 2),
        w_structure=round(rng.uniform(0.30, 1.40), 2),
        w_momentum=round(rng.uniform(0.10, 1.20), 2),
        w_volatility=round(rng.uniform(0.10, 1.00), 2),
        w_sweep_quality=round(rng.uniform(0.40, 1.50), 2),
        min_confluence=round(rng.uniform(0.45, 0.82), 3),
        min_target_room_atr=round(rng.uniform(0.6, 2.6), 2),
        min_atr_pct=round(rng.uniform(0.05, 0.45), 3),
        max_atr_pct=round(rng.uniform(0.85, 0.99), 3),
        sweep_min_pen=round(rng.uniform(0.02, 0.22), 3),
        sweep_max_pen=round(rng.uniform(0.80, 2.00), 2),
        sweep_reclaim=rng.randint(2, 5),
        min_stop_atr=round(rng.uniform(0.8, 3.0), 2),
        max_stop_atr=round(rng.uniform(3.0, 6.5), 2),
        first_target_r=round(rng.uniform(0.4, 3.2), 2),
        scale_out=round(rng.uniform(0.0, 0.85), 2),
        trail_atr=round(rng.uniform(0.7, 3.2), 2),
        kalman_buf=round(rng.uniform(0.0, 0.9), 2),
        endurance_min_r=round(rng.uniform(1.0, 4.5), 2),
        breakeven_arm_r=rng.choice([0.0, 0.0, 0.0, 0.6, 1.0, 1.4]),
        time_stop_bars=rng.choice([12, 18, 24, 36, 48, 72]),
        cooldown_bars=rng.choice([0, 3, 8, 15, 25]),
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Result:
    trades: int = 0
    expectancy: float = 0.0
    sum_r: float = 0.0
    win_rate: float = 0.0
    trades_per_day: float = 0.0
    max_dd_pct: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    mean_hold: float = 0.0
    worst: float = 0.0


def build_engine(variant: Variant):
    base = profile_for(AssetClass.MICRO_FUTURES)
    weights = ConfluenceWeights(
        sweep_quality=variant.w_sweep_quality,
        order_flow=variant.w_order_flow,
        structure=variant.w_structure,
        volatility=variant.w_volatility,
        location=variant.w_location,
        momentum=variant.w_momentum,
        sentiment=0.25,
        ml=0.0,
    )
    profile = replace(
        base,
        weights=weights,
        min_confluence=variant.min_confluence,
        min_atr_percentile=variant.min_atr_pct,
        max_atr_percentile=variant.max_atr_pct,
        sweep_min_penetration_atr=variant.sweep_min_pen,
        sweep_max_penetration_atr=variant.sweep_max_pen,
        sweep_reclaim_bars=variant.sweep_reclaim,
        time_stop_bars=variant.time_stop_bars,
        cooldown_bars_after_exit=variant.cooldown_bars,
    )
    policy = HybridExit(HybridParams(
        min_stop_atr=variant.min_stop_atr,
        max_stop_atr=variant.max_stop_atr,
        first_target_r=variant.first_target_r,
        scale_out_fraction=variant.scale_out,
        trail_distance_atr=variant.trail_atr,
        kalman_trail_buffer_atr=variant.kalman_buf,
        endurance_min_r=variant.endurance_min_r,
        breakeven_arm_r=variant.breakeven_arm_r,
    ))
    engine = IcarusEngine(profile, exit_policy=policy, timeframe=variant.timeframe)
    engine.confluence.min_target_room_atr = variant.min_target_room_atr
    return engine


def evaluate(variant: Variant, bars) -> Result:
    signal_module.ConfluenceEngine._location_score = staticmethod(
        LOCATION_MODES[variant.location_mode])
    engine = build_engine(variant)
    for bar in bars:
        engine.on_bar(bar)
    trades = engine.blotter.trades
    if not trades:
        return Result()

    r = [t.r for t in trades]
    wins = [x for x in r if x > 0.0]
    losses = [x for x in r if x <= 0.0]
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    days = max((bars[-1].ts - bars[0].ts).total_seconds() / 86400.0, 1e-9)

    return Result(
        trades=len(trades),
        expectancy=st.fmean(r),
        sum_r=sum(r),
        win_rate=100.0 * len(wins) / len(trades),
        trades_per_day=len(trades) / days,
        max_dd_pct=100.0 * engine.blotter.max_drawdown / engine.blotter.starting_equity,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        avg_win=st.fmean(wins) if wins else 0.0,
        avg_loss=st.fmean(losses) if losses else 0.0,
        mean_hold=st.fmean([t.bars_held for t in trades]),
        worst=min(r),
    )


# Tapes are built once in the parent and inherited by forked workers.
TAPES: dict[tuple[str, str], list] = {}


def _worker(payload):
    variant, tape_key = payload
    try:
        return variant, asdict(evaluate(variant, TAPES[(tape_key, variant.timeframe)]))
    except Exception as exc:                       # a variant must never kill the sweep
        return variant, {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def build_tapes(screen_bars: int, full_bars: int, tune_seed: int, hold_seed: int) -> None:
    """Generate every tape once, in the parent, so forked workers share them."""
    for tf in TIMEFRAME_CHOICES:
        tune_src = synthetic_for(AssetClass.MICRO_FUTURES, full_bars, seed=tune_seed, minutes=2)
        hold_src = synthetic_for(AssetClass.MICRO_FUTURES, full_bars, seed=hold_seed, minutes=2)
        TAPES[("screen", tf)] = resample(tune_src[:screen_bars], tf)
        TAPES[("tune", tf)] = resample(tune_src, tf)
        TAPES[("hold", tf)] = resample(hold_src, tf)


def run_stage(variants, tape_key: str, workers: int):
    with mp.Pool(workers) as pool:
        return pool.map(_worker, [(v, tape_key) for v in variants], chunksize=1)


def passes(res: dict, *, min_trades: int, min_exp: float,
           max_tpd: float, min_tpd: float, min_win: float) -> bool:
    if "error" in res or res["trades"] < min_trades:
        return False
    return (res["expectancy"] >= min_exp
            and min_tpd <= res["trades_per_day"] <= max_tpd
            and res["win_rate"] >= min_win)


def fmt(v: Variant, res: dict) -> str:
    return (f"{v.timeframe:>3s} {v.location_mode[:4]:>4s} "
            f"n={res['trades']:4d} tpd={res['trades_per_day']:4.2f} "
            f"win={res['win_rate']:5.1f}% exp={res['expectancy']:+6.3f}R "
            f"PF={min(res['profit_factor'], 99):5.2f} DD={res['max_dd_pct']:5.2f}% "
            f"hold={res['mean_hold']:5.1f} worst={res['worst']:+5.2f}R")
