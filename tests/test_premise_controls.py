"""The control group has to neutralise drift, or drift is reported as edge.

This exists because it did not. An earlier `matched_controls` used
`set(directions)`, collapsing a bucket of 90 long sweeps and 10 short ones into
a 50/50 control mix. On a trending tape the sweeps then carried the trend while
the controls averaged it away, and the difference -- pure drift -- came back as
a +1.3 ATR "effect" in a rising market and -1.4 ATR in a falling one. Equal and
opposite across two instruments is the signature of measuring trend, not
structure, and only a positive control catches it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from icarus.data import Bar
from tools.premise import Tape, forward_return, matched_controls, Sweep


def _trending_tape(n: int = 3000, drift: float = 0.5) -> list[Bar]:
    """A tape with a strong, perfectly steady uptrend and no structure at all.

    Nothing here rewards a sweep: price simply rises every bar. Any method that
    reports an edge on this tape is reporting the drift.
    """
    start = datetime(2025, 1, 6, 14, 30, tzinfo=timezone.utc)
    bars, price = [], 20_000.0
    for i in range(n):
        price += drift
        bars.append(Bar(ts=start + timedelta(minutes=5 * i),
                        open=price - drift, high=price + 1.0,
                        low=price - drift - 1.0, close=price, volume=100.0))
    return bars


def test_controls_cancel_drift_when_sweeps_lean_one_way():
    tape = Tape(_trending_tape())
    # A lopsided book of sweeps, as a trending market actually produces.
    sweeps = [Sweep(index=i, direction=+1, reference=0.0,
                    atr=tape.atr[i], minute=tape.minute[i])
              for i in range(100, 2000, 7)]
    sweeps += [Sweep(index=i, direction=-1, reference=0.0,
                     atr=tape.atr[i], minute=tape.minute[i])
               for i in range(103, 2000, 63)]

    horizon = 12
    treated = [v for v in (forward_return(tape, s.index, horizon, s.direction)
                           for s in sweeps) if v is not None]
    controls = matched_controls(tape, sweeps, horizon)

    assert treated and controls
    effect = sum(treated) / len(treated) - sum(controls) / len(controls)
    # The tape has no structure, so whatever the drift is, matched controls
    # must remove nearly all of it. The broken version scored about +1.3 here.
    assert abs(effect) < 0.25, (
        f"drift leaked into the effect: {effect:+.3f} ATR on a tape with no "
        f"structure (treated {sum(treated)/len(treated):+.3f}, "
        f"controls {sum(controls)/len(controls):+.3f})")


def test_a_balanced_book_also_cancels():
    """With no directional lean the control mix is symmetric and nets to zero."""
    tape = Tape(_trending_tape())
    sweeps = ([Sweep(i, +1, 0.0, tape.atr[i], tape.minute[i]) for i in range(100, 2000, 11)]
              + [Sweep(i, -1, 0.0, tape.atr[i], tape.minute[i]) for i in range(104, 2000, 11)])
    controls = matched_controls(tape, sweeps, 12)
    assert controls
    assert abs(sum(controls) / len(controls)) < 0.05
