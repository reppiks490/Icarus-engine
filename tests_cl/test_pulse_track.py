# CL (Claude, Anthropic) — 2026-10-04 — tests for cl_lab.pulse_track (THE PULSE OF ICARUS through the CL gates)
import os

import numpy as np
import pytest

from cl_lab import pulse_track, validate

pytestmark = pytest.mark.skipif(not os.path.exists(pulse_track.TAPE), reason="MNQ 20m tape not present")


@pytest.fixture(scope="module")
def raw():
    from icarus.data import load_csv
    return load_csv(pulse_track.TAPE)[:2500]


def test_daily_aggregation_conserves_profit_and_is_deterministic(raw):
    a = pulse_track.run_variant(raw, "HA_REAL_FILLS", 0.85, 1)
    b = pulse_track.run_variant(raw, "HA_REAL_FILLS", 0.85, 1)
    assert [(t.exit_ts, t.profit) for t in a] == [(t.exit_ts, t.profit) for t in b]
    dates = sorted(set(pulse_track.session_date_of([t.exit_ts for t in a])))
    pnl, cnt = pulse_track.daily_pnl(a, dates)
    assert pnl.sum() == pytest.approx(sum(t.profit for t in a)) and cnt.sum() == len(a)


def test_heikin_ashi_fill_artifact_is_never_promotable():
    dates = [np.datetime64("2025-01-02") + np.timedelta64(i, "D") for i in range(400)]
    dates = [d.astype("datetime64[D]").item() for d in dates]
    x = np.full(400, 1000.0)
    rec = validate.evaluate_external(dates, {"HA_HA_FILLS": x}, {"HA_HA_FILLS": np.ones(400, int)}, {},
                                     ("HA_REAL_FILLS", "CANDLES"), 100, 0.003)
    assert rec["HA_HA_FILLS"]["status"] == "ARTIFACT_REFERENCE"
