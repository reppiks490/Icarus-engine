import gzip
import os

import numpy as np
import pandas as pd

from cl_lab import depth_test as dt


def _write(path, frame, index=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt") as f:
        frame.to_csv(f, index=index)


def _cache(tmp_path, days=24, effect=0.0, ic=0.0, seed=0):
    """Synthetic NQ days. ``effect``: ticks by which SLOW-refill sweeps out-move FAST ones.
    ``ic``: how much DI(t) drives the t+1 -> t+15 midrange move. Each day gets its own drift."""
    rng = np.random.default_rng(seed)
    root = tmp_path / "cache"
    for i in range(days):
        day = (pd.Timestamp("2026-10-12") + pd.offsets.BDay(i)).date().isoformat()
        n = 40
        refill = rng.choice([0.2, 1.4], size=n)
        drift = rng.normal(0, 3)
        move = drift + rng.normal(0, 4, n) + np.where(refill < dt.SLOW, effect / 2, -effect / 2)
        ev = pd.DataFrame(dict(ts=np.arange(n), dir=1, levels_swept=2, refill_5s=refill, move_30s=move,
                               move_60s=move, move_300s=move))
        _write(str(root / "resilience/primary/nq" / f"{day}.csv.gz"), ev)
        m = 400
        di = rng.uniform(-0.5, 0.5, m)
        steps = rng.normal(0, 1, m)
        for lag in range(2, 7):                           # DI at t moves price over t+2..t+6, inside the outcome window
            steps[lag:] += ic * di[:-lag]
        mid = 20000 + np.cumsum(steps)
        bid = 100 * (1 + di)
        ask = 100 * (1 - di)
        f = pd.DataFrame(dict(depth10_bid_mean=bid, depth10_ask_mean=ask, price_min=mid - 0.25, price_max=mid + 0.25),
                         index=pd.date_range(day, periods=m, freq="min").astype(str))
        _write(str(root / "features/primary/mbp10/nq" / f"{day}.csv.gz"), f, index=True)
    return str(root)


def test_empty_cache_is_insufficient_not_rejected(tmp_path):
    out = dt.run(str(tmp_path / "nothing"), perms=50)
    assert out["D1-A"]["status"] == "INSUFFICIENT_DATA"
    assert out["D1-B"]["status"] == "INSUFFICIENT_DATA"
    assert out["execution_authorized"] is False


def test_too_few_days_is_insufficient(tmp_path):
    out = dt.run(_cache(tmp_path, days=5, effect=20.0), perms=50)
    assert out["D1-A"]["status"] == "INSUFFICIENT_DATA"


def test_null_is_not_confirmed(tmp_path):
    out = dt.run(_cache(tmp_path, effect=0.0, ic=0.0, seed=1), perms=300)
    assert out["D1-A"]["status"] != "D1_CONFIRMED"
    assert out["D1-B"]["status"] != "D1_CONFIRMED"


def test_planted_tradeable_sweep_effect_is_confirmed(tmp_path):
    out = dt.run(_cache(tmp_path, effect=12.0, seed=2), perms=300)
    assert out["D1-A"]["status"] == "D1_CONFIRMED", out["D1-A"]
    assert out["D1-A"]["effect"] > dt.TICKS_COST


def test_planted_small_effect_is_significant_but_not_tradeable(tmp_path):
    out = dt.run(_cache(tmp_path, effect=3.0, seed=3), perms=300)
    assert out["D1-A"]["status"] == "SIGNIFICANT_NOT_TRADEABLE", out["D1-A"]


def test_day_drift_alone_cannot_create_the_sweep_effect(tmp_path):
    # every day carries a large drift, but FAST/SLOW are balanced within days: no effect may appear
    out = dt.run(_cache(tmp_path, effect=0.0, seed=4), perms=300)
    assert out["D1-A"]["p"] > 0.01


def test_planted_book_imbalance_is_detected(tmp_path):
    out = dt.run(_cache(tmp_path, ic=1.0, seed=5), perms=200)
    assert out["D1-B"]["status"] == "D1_CONFIRMED", out["D1-B"]


def test_outcome_window_excludes_the_feature_minute(tmp_path):
    # a DI that only explains minute t's own price must not count: shift the planted link into the same minute
    root = _cache(tmp_path, days=24, ic=0.0, seed=6)
    for p in (tmp_path / "cache/features/primary/mbp10/nq").iterdir():
        f = pd.read_csv(p, index_col=0)
        di = (f["depth10_bid_mean"] - f["depth10_ask_mean"]) / (f["depth10_bid_mean"] + f["depth10_ask_mean"])
        f["price_min"] = f["price_min"] + 40 * di
        f["price_max"] = f["price_max"] + 40 * di
        _write(str(p), f, index=True)
    out = dt.run(root, perms=200)
    assert out["D1-B"]["status"] != "D1_CONFIRMED"
