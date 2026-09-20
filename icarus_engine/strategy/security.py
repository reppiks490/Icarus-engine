"""request.security() connections — the HTF/LTF chains the script reads (§2/§3).

Each chain aggregates 1-minute bars into its own timeframe and runs the
script's two helper functions on every COMPLETED bar of that timeframe:

    f_htf_combined():  ta.supertrend(3, 14) direction, ADX-based regime proxy
    f_ltf_combined():  the same + ta.barssince(direction flip)

with the confirmed-bar idiom the script uses (`expr[1]` + lookahead_on):

  * higher timeframe than the chart → the value of the last HTF bar that
    closed BEFORE the HTF bar containing the chart bar (identical on
    historical and realtime bars);
  * lower timeframe than the chart → the value at the intrabar preceding
    the chart bar's last intrabar (documented assumption A5).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..pine import ta
from ..pine.series import NAN, na
from ..pine.timeframe import Aggregator, Bar, bucket_start


class _HA:
    """TradingView Heikin Ashi (first bar: open = (o+c)/2), quantised to the tick like TradingView's HA series."""
    def __init__(self, mintick=None):
        self.prev_o = None
        self.prev_c = None
        self.mintick = mintick

    def _q(self, x: float) -> float:
        return round(round(x / self.mintick) * self.mintick, 10) if self.mintick else x

    def transform(self, b: Bar) -> Bar:
        c = self._q((b.o + b.h + b.l + b.c) / 4.0)
        o = self._q((b.o + b.c) / 2.0 if self.prev_o is None else (self.prev_o + self.prev_c) / 2.0)
        h = max(b.h, o, c); l = min(b.l, o, c)
        self.prev_o, self.prev_c = o, c
        return Bar(b.ts, o, h, l, c, b.v)


class TFChain:
    """`ha=True` reproduces TradingView on a Heikin Ashi chart: `request.security(syminfo.tickerid, ...)`
    receives the HA-transformed bars of the requested timeframe (the ticker id carries the chart's HA
    modifier; only `ticker.standard()` would strip it) - see PARITY.md A3/A11 and the audit."""

    def __init__(self, minutes: int, bucket_fn=None, end_fn=None, ha: bool = False, ltf_intrabar: str = "first", mintick=None):
        self.minutes = int(minutes)
        self.bucket_fn = bucket_fn or bucket_start
        self.agg = Aggregator(self.minutes, self.bucket_fn, end_fn)
        self.ha = _HA(mintick) if ha else None
        self.ltf_intrabar = ltf_intrabar
        self.st = ta.SUPERTREND(3.0, 14)
        self.dmi = ta.DMI(14, 14)
        self.bsf = ta.BARSSINCE()
        self.prev_dir = NAN
        self.bars = 0
        # per completed bucket: (dir, bsf, regime) evaluated on that bar
        self.by_bucket: Dict[int, Tuple[float, float, float]] = {}
        self.order: List[int] = []
        self.last_completed: Optional[int] = None
        self.last_bar: Optional[Bar] = None

    # ── feeding ──
    def on_completed_bar(self, b: Bar) -> None:
        if self.ha is not None:
            b = self.ha.transform(b)
        _, d = self.st.update(b.h, b.l, b.c)
        _, _, adx = self.dmi.update(b.h, b.l, b.c)
        reg = NAN if na(adx) else min(max((adx - 15.0) / 20.0, 0.0), 1.0)
        flipped = (not na(self.prev_dir)) and d != self.prev_dir
        bsf = self.bsf.update(flipped)
        self.prev_dir = d
        self.bars += 1
        bk = self.bucket_fn(b.ts, self.minutes)
        self.by_bucket[bk] = (float(d), bsf, reg)
        self.order.append(bk)
        self.last_completed = bk
        self.last_bar = b
        if len(self.order) > 4000:                        # bounded memory
            for old in self.order[:1000]:
                self.by_bucket.pop(old, None)
            self.order = self.order[1000:]

    def push_sub_bar(self, b: Bar, sub_minutes: int = 1) -> List[Bar]:
        done = self.agg.push(b, sub_minutes)
        for cb in done:
            self.on_completed_bar(cb)
        return done

    def flush_if_stale(self, now_ts: float) -> None:
        cb = self.agg.flush_if_stale(now_ts)
        if cb is not None:
            self.on_completed_bar(cb)

    # ── lookups (Pine request.security confirmed-bar idiom) ──
    def _value_before_bucket(self, bk: int) -> Tuple[float, float, float]:
        """Values of the last completed bucket strictly before `bk`."""
        # walk back from the end of `order` (recent first)
        for j in range(len(self.order) - 1, -1, -1):
            k = self.order[j]
            if k < bk:
                return self.by_bucket[k]
        return (NAN, NAN, NAN)

    def htf_values(self, chart_ts: int) -> Tuple[float, float]:
        """[_d[1], _reg[1]] for a chart bar opening at chart_ts (this TF >= chart TF)."""
        bk = self.bucket_fn(chart_ts, self.minutes)
        d, _, reg = self._value_before_bucket(bk)
        return d, reg

    def ltf_values(self, chart_ts: int, chart_minutes: int, chart_end: Optional[int] = None) -> Tuple[float, float, float]:
        """[_d[1], _bsf[1], _reg[1]] for a chart bar of `chart_minutes` opening at chart_ts.
        TradingView, `lookahead_on` on a lower timeframe: historical bars return the FIRST intrabar's value
        ("it will return the first available intrabar from the chart period"), realtime bars the LAST one.
        `ltf_intrabar="first"` reproduces the backtests the owner validated; "last" = TradingView live."""
        if self.minutes >= chart_minutes:
            bk = self.bucket_fn(chart_ts, self.minutes)
            return self._value_before_bucket(bk)
        if self.ltf_intrabar == "last":
            chart_end = chart_end or (chart_ts + chart_minutes * 60)     # a session's stub bar ends at the session close
            last_intrabar = self.bucket_fn(chart_end - 1, self.minutes)   # last LTF bucket opening inside the chart bar
            return self._value_before_bucket(last_intrabar)
        first_intrabar = self.bucket_fn(chart_ts, self.minutes)           # [1] of the first intrabar = last LTF bar closed before the chart bar
        return self._value_before_bucket(first_intrabar)

    def state(self) -> Dict[str, object]:
        if self.last_completed is None:
            return {"tf": self.minutes, "bars": self.bars}
        d, bsf, reg = self.by_bucket[self.last_completed]
        return {"tf": self.minutes, "bars": self.bars, "dir": d, "bsf": bsf, "regime": reg, "last": self.last_completed}
