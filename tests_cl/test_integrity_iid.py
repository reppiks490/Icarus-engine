# CL (Claude, Anthropic) — 2026-10-05 — cl-data-3: instrument_id switches are exact rolls, whatever their size
import numpy as np
import pandas as pd

from cl_lab import bars, integrity


def _tape(start, end, switch_at=None, spread=5.0, with_iid=True):
    idx = pd.date_range(start, end, freq="5min", tz="UTC", inclusive="left")
    idx = idx[idx.dayofweek < 5]
    rng = np.random.default_rng(1)
    px = 15000 + np.cumsum(rng.normal(0, 0.5, len(idx)))
    iid = np.full(len(idx), 100.0)
    if switch_at is not None:
        k = int(np.searchsorted(idx, pd.Timestamp(switch_at)))
        px[k:] += spread                                   # new contract trades `spread` points higher
        iid[k:] = 200.0
    df = pd.DataFrame(dict(open=px, high=px + 1, low=px - 1, close=px, volume=1.0), index=idx)
    if with_iid:
        df["instrument_id"] = iid
    return bars.annotate(df)


def test_small_roll_is_detected_and_removed_by_back_adjustment():
    adf = _tape("2015-02-02", "2015-04-10", switch_at="2015-03-12T00:00:00Z", spread=5.0)   # ~3 bp: under 40 bp
    rolls = integrity.detect_rolls(adf, None)
    det = [r for r in rolls if r["status"] == "DETECTED"]
    assert len(det) == 1 and det[0]["method"] == "instrument_id" and det[0]["quarter"] == "2015-03"
    assert det[0]["sized_by"] == "adjacent_bars" and abs(det[0]["delta"] - 5.0) < 2.0
    adj = integrity.back_adjust(adf, rolls)
    k = det[0]["pos"]
    assert abs(adj["open"].iloc[k] - adj["close"].iloc[k - 1]) < 2.0             # the gap is gone
    assert integrity.summary(rolls)["data_version"] == "cl-data-3"


def test_without_instrument_id_the_cl_data_2_threshold_still_applies():
    adf = _tape("2015-02-02", "2015-04-10", switch_at="2015-03-12T00:00:00Z", spread=5.0, with_iid=False)
    rolls = integrity.detect_rolls(adf, None)
    assert not [r for r in rolls if r["status"] == "DETECTED"]                  # 5 points is below 40 bp


def test_flip_back_is_two_switches_that_cancel():
    adf = _tape("2015-02-02", "2015-04-10", switch_at="2015-03-11T00:00:00Z", spread=5.0)
    k2 = int(np.searchsorted(adf.index, pd.Timestamp("2015-03-12T00:00:00Z")))
    adf.iloc[k2:, adf.columns.get_loc("instrument_id")] = 100.0                 # volume rank flips back for a day
    for col in ("open", "high", "low", "close"):
        adf.iloc[k2:, adf.columns.get_loc(col)] -= 5.0
    k3 = int(np.searchsorted(adf.index, pd.Timestamp("2015-03-13T00:00:00Z")))
    adf.iloc[k3:, adf.columns.get_loc("instrument_id")] = 200.0
    for col in ("open", "high", "low", "close"):
        adf.iloc[k3:, adf.columns.get_loc(col)] += 5.0
    det = [r for r in integrity.detect_rolls(adf, None) if r["status"] == "DETECTED"]
    assert len(det) == 3 and abs(sum(r["delta"] for r in det) - 5.0) < 3.0


def test_quarter_cut_by_the_tape_start_is_adjusted_once():
    # tape starts 2010-06-07 (Databento's first week); the June roll falls inside the partial quarter
    adf = _tape("2010-06-07", "2010-07-30", switch_at="2010-06-10T00:00:00Z", spread=120.0)    # big enough for 40 bp
    rolls = integrity.detect_rolls(adf, None)
    det = [r for r in rolls if r["status"] == "DETECTED"]
    assert len(det) == 1 and det[0]["method"] == "instrument_id"
    adj = integrity.back_adjust(adf, rolls)
    k = det[0]["pos"]
    assert abs(adj["open"].iloc[k] - adj["close"].iloc[k - 1]) < 2.0
