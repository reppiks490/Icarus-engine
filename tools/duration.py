"""Hold time in minutes, converted to bars per timeframe.

A bar count is not a duration. Thirty bars is two and a half hours on a 5m
chart and ten hours on a 20m chart -- the same number describing two completely
different systems. Every hold criterion in this repo was written as a flat bar
count, which is why a 25.4-bar mean at 20m got reported as an intraday hold
when it is eight and a half hours, more than double the operator's ceiling.

The operator's spec, in their words: no more than four hours, around two for
the 5m / 2m / 1m charts. So duration is the primitive and bars are derived.

Two things scale differently and both matter:

  THE CEILING is wall-clock and does not care about the chart. Four hours of
  exposure is four hours of exposure whether it took 12 bars or 240 to get
  there, because what is at risk is time in the market, not bars printed.

  THE TARGET tracks the chart, because someone reading a 1m chart is trading a
  faster phenomenon than someone reading 30m. Two hours on the fast charts,
  drifting toward the ceiling on the slow ones.

  THE FLOOR has to satisfy both: long enough in minutes that it is not a
  scalp, and long enough in bars that the trade actually developed rather than
  resolving inside the entry bar's own noise.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HoldSpec:
    """The operator's duration envelope, in minutes."""

    ceiling_minutes: float = 240.0      # 4h, hard, every timeframe
    fast_target_minutes: float = 120.0  # ~2h on 1m/2m/5m
    slow_target_minutes: float = 240.0  # up to the ceiling on 20m/30m
    fast_tf: float = 5.0                # at or below this, "fast chart"
    slow_tf: float = 20.0               # at or above this, "slow chart"
    floor_minutes: float = 20.0         # below this it is a scalp
    floor_bars: int = 6                 # and it must have had room to develop

    def target_minutes(self, tf_minutes: float) -> float:
        """Typical hold for this chart, interpolated between fast and slow."""
        if tf_minutes <= self.fast_tf:
            return self.fast_target_minutes
        if tf_minutes >= self.slow_tf:
            return self.slow_target_minutes
        # Linear across the middle so 10m lands between the two rather than
        # snapping to whichever side it is nearer.
        span = self.slow_tf - self.fast_tf
        frac = (tf_minutes - self.fast_tf) / span
        return self.fast_target_minutes + frac * (self.slow_target_minutes - self.fast_target_minutes)

    def bars(self, tf_minutes: float) -> tuple[int, int, int]:
        """(floor, target, ceiling) in BARS for this timeframe."""
        ceiling = max(1, round(self.ceiling_minutes / tf_minutes))
        target = max(1, round(self.target_minutes(tf_minutes) / tf_minutes))
        floor = max(self.floor_bars, round(self.floor_minutes / tf_minutes))
        # A chart so slow that the floor would exceed the ceiling is a chart
        # this envelope cannot express; keep them ordered rather than silently
        # inverting the test.
        floor = min(floor, ceiling)
        target = min(max(target, floor), ceiling)
        return floor, target, ceiling

    def horizons(self, tf_minutes: float) -> list[int]:
        """Forward-return horizons worth testing on this chart, in bars.

        Spread across the envelope rather than a fixed bar grid, so 20m is not
        being asked about a ten-hour horizon it would never trade.
        """
        floor, target, ceiling = self.bars(tf_minutes)
        candidates = {floor, round(target / 2), target, round((target + ceiling) / 2), ceiling}
        return sorted(h for h in candidates if h >= 1)

    def describe(self, tf_minutes: float) -> str:
        floor, target, ceiling = self.bars(tf_minutes)
        return (f"{tf_minutes:g}m: floor {floor}b/{floor * tf_minutes:g}min  "
                f"target {target}b/{target * tf_minutes:g}min  "
                f"ceiling {ceiling}b/{ceiling * tf_minutes:g}min")


HOLD = HoldSpec()
