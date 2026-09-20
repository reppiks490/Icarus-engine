"""The comparison itself has to be sound, or every downstream gate is decoration.

FDR control, matched samples and two-span agreement all assume the treated and
control groups are comparable. None of them can see a biased comparison. Two
versions of this estimator shipped a biased one, and both produced IWM at
+1.39 ATR against SPY at -1.51 ATR -- equal and opposite, same asset class,
over windows where one instrument rose and the other fell. That is drift, and
it survived every statistical gate in the design.

Only a synthetic tape where the answer is known by construction catches it.
"""

from datetime import datetime, timedelta, timezone

from icarus.data import Bar
from tools.premise import Sweep, Tape, stratified_effect


def _tape(n: int, drift_for) -> list[Bar]:
    """A tape with NO structure -- price is a pure function of the clock.

    Nothing here rewards a sweep. Any method reporting an effect is reporting
    the drift that `drift_for` puts in.
    """
    start = datetime(2025, 1, 6, 9, 0, tzinfo=timezone.utc)
    bars, price = [], 20_000.0
    for i in range(n):
        ts = start + timedelta(minutes=5 * i)
        price += drift_for(ts)
        bars.append(Bar(ts=ts, open=price - 0.5, high=price + 1.0,
                        low=price - 1.5, close=price, volume=100.0))
    return bars


def _sweeps(tape: Tape, indices, direction: int) -> list[Sweep]:
    return [Sweep(index=i, direction=direction, reference=0.0,
                  atr=tape.atr[i], minute=tape.minute[i]) for i in indices]


def test_a_lopsided_sweep_book_does_not_pick_up_uniform_drift():
    """90/10 long sweeps on a steadily rising tape must net to zero.

    The first broken version used set(directions), turning a 90/10 book into a
    50/50 control mix so the sweeps kept the drift the controls averaged away.
    """
    tape = Tape(_tape(3000, lambda ts: 0.5))
    sweeps = (_sweeps(tape, range(100, 2000, 7), +1)
              + _sweeps(tape, range(103, 2000, 63), -1))
    effect, treated, controls = stratified_effect(tape, sweeps, 12)
    assert treated and controls
    assert abs(effect) < 0.25, f"uniform drift leaked: {effect:+.3f} ATR"


def test_sweeps_concentrated_in_one_stratum_do_not_pick_up_its_drift():
    """The bug matching alone cannot catch, isolated.

    Here the morning rises hard and the afternoon falls hard, and the sweeps
    sit almost entirely in the morning while control bars are spread across
    both. Matching each control bar to a stratum is not enough -- pooling the
    two groups afterwards still compares a morning-heavy treated mean against
    an all-day control mean, and reports the morning's drift as edge. Only
    comparing WITHIN strata removes it.
    """
    def drift(ts):
        return 1.0 if ts.hour < 13 else -1.0

    bars = _tape(4000, drift)
    tape = Tape(bars)
    morning = [i for i in range(60, len(bars) - 60)
               if bars[i].ts.hour < 13 and i % 3 == 0]
    afternoon = [i for i in range(60, len(bars) - 60)
                 if bars[i].ts.hour >= 13 and i % 40 == 0]
    assert len(morning) > 200 and len(afternoon) > 10

    sweeps = _sweeps(tape, morning, +1) + _sweeps(tape, afternoon, +1)
    effect, treated, controls = stratified_effect(tape, sweeps, 12)
    assert treated and controls
    assert abs(effect) < 0.35, (
        f"stratum-concentration drift leaked: {effect:+.3f} ATR on a tape "
        f"whose only structure is the time of day")


def test_a_balanced_book_nets_to_zero():
    tape = Tape(_tape(3000, lambda ts: 0.5))
    sweeps = (_sweeps(tape, range(100, 2000, 11), +1)
              + _sweeps(tape, range(104, 2000, 11), -1))
    effect, _, _ = stratified_effect(tape, sweeps, 12)
    assert abs(effect) < 0.05


def test_a_real_effect_is_still_detected():
    """The estimator must not be so conservative it erases genuine signal.

    A control that removes everything is as useless as one that removes
    nothing. The planted move is SPARSE -- spaced far wider than the horizon --
    so it is a post-sweep excursion rather than a trend. An earlier version of
    this test spaced the plants closer together than the horizon they were
    measured over, which merged them into a continuous drift; the estimator
    removed it, correctly, and the test failed for the right reason.
    """
    horizon, stride = 12, 40
    plants = set(range(200, 2800, stride))

    def drift(ts):
        return 0.0

    bars = _tape(3000, drift)
    # Rebuild with an upward push only in the bars FOLLOWING each plant.
    pushed, level = [], 0.0
    for i, b in enumerate(bars):
        if any(p < i <= p + horizon for p in plants):
            level += 1.5
        pushed.append(Bar(ts=b.ts, open=b.open + level, high=b.high + level,
                          low=b.low + level, close=b.close + level,
                          volume=b.volume))
    tape = Tape(pushed)
    effect, _, _ = stratified_effect(tape, _sweeps(tape, sorted(plants), +1), horizon)
    assert effect > 0.30, f"a planted effect was erased: {effect:+.3f} ATR"
