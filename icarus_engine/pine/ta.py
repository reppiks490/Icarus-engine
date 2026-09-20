"""Pine `ta.*` built-ins as stateful objects with Pine's exact seeding rules.

Every object is fed exactly once per bar with `update(value)` and returns the
indicator's value for that bar. Seeding follows the Pine reference
implementations:

  ta.ema / ta.rma   first value = SMA of the first `length` inputs, then recursive
  ta.atr            rma(tr(true), length)
  ta.dmi            Wilder DM/DI with rma + fixnan, ADX = rma(|DI+ - DI-| / sum)
  ta.rsi            100 - 100/(1 + rma(up)/rma(down)) with the 0-guards
  ta.stdev          population (biased) standard deviation
  ta.supertrend     the reference implementation (direction -1 = up-trend)
  ta.pivothigh/low  src[right] equals the window extreme (ties count)
  ta.vwap           session-anchored sum(pv)/sum(v), reset when `new_session` is true
  ta.percentrank    % of the previous `length` values <= current
  ta.barssince      bars since the condition was last true (na if never)
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional

from .series import NAN, na, nz, fixnan


class SMA:
    def __init__(self, length: int):
        self.n = max(1, int(length))
        self.buf: deque = deque(maxlen=self.n)

    def update(self, v: float) -> float:
        self.buf.append(v)
        if len(self.buf) < self.n:
            return NAN
        s = 0.0
        for x in self.buf:
            if na(x):
                return NAN
            s += x
        return s / self.n


class EMA:
    """alpha = 2/(n+1); Pine: sum := na(sum[1]) ? ta.sma(src, n) : alpha*src + (1-alpha)*nz(sum[1])"""
    def __init__(self, length: int, alpha: Optional[float] = None):
        self.n = max(1, int(length))
        self.alpha = alpha if alpha is not None else 2.0 / (self.n + 1)
        self.sma = SMA(self.n)
        self.prev = NAN

    def update(self, v: float) -> float:
        seed = self.sma.update(v)
        if na(self.prev):
            out = seed
        else:
            out = self.alpha * v + (1.0 - self.alpha) * nz(self.prev)
        self.prev = out
        return out


class RMA(EMA):
    def __init__(self, length: int):
        super().__init__(length, alpha=1.0 / max(1, int(length)))


class TR:
    """ta.tr(true): na close[1] -> high-low."""
    def __init__(self):
        self.c1 = NAN

    def update(self, h: float, l: float, c: float) -> float:
        if na(self.c1):
            tr = h - l
        else:
            tr = max(h - l, abs(h - self.c1), abs(l - self.c1))
        self.c1 = c
        return tr


class ATR:
    def __init__(self, length: int):
        self.tr = TR()
        self.rma = RMA(length)

    def update(self, h: float, l: float, c: float) -> float:
        return self.rma.update(self.tr.update(h, l, c))


class DMI:
    """Returns (plus, minus, adx) - the ta.dmi reference implementation."""
    def __init__(self, di_len: int, adx_smooth: int):
        self.h1 = NAN
        self.l1 = NAN
        self.tr = TR()
        self.rma_tr = RMA(di_len)
        self.rma_p = RMA(di_len)
        self.rma_m = RMA(di_len)
        self.rma_adx = RMA(adx_smooth)
        self.plus_fix = NAN
        self.minus_fix = NAN

    def update(self, h: float, l: float, c: float):
        up = NAN if na(self.h1) else h - self.h1
        down = NAN if na(self.l1) else self.l1 - l
        self.h1, self.l1 = h, l
        plus_dm = NAN if na(up) else (up if (up > down and up > 0) else 0.0)
        minus_dm = NAN if na(down) else (down if (down > up and down > 0) else 0.0)
        trur = self.rma_tr.update(self.tr.update(h, l, c))
        rp = self.rma_p.update(plus_dm)
        rm = self.rma_m.update(minus_dm)
        plus_raw = NAN if (na(rp) or na(trur) or trur == 0) else 100.0 * rp / trur
        minus_raw = NAN if (na(rm) or na(trur) or trur == 0) else 100.0 * rm / trur
        self.plus_fix = fixnan(self.plus_fix, plus_raw)
        self.minus_fix = fixnan(self.minus_fix, minus_raw)
        plus, minus = self.plus_fix, self.minus_fix
        if na(plus) or na(minus):
            dx = NAN
        else:
            s = plus + minus
            dx = abs(plus - minus) / (1.0 if s == 0 else s)
        adx = self.rma_adx.update(dx)
        return plus, minus, (NAN if na(adx) else 100.0 * adx)


class RSI:
    def __init__(self, length: int):
        self.prev = NAN
        self.up = RMA(length)
        self.dn = RMA(length)

    def update(self, v: float) -> float:
        ch = NAN if na(self.prev) else v - self.prev
        self.prev = v
        u = NAN if na(ch) else max(ch, 0.0)
        d = NAN if na(ch) else max(-ch, 0.0)
        ru = self.up.update(u)
        rd = self.dn.update(d)
        if na(ru) or na(rd):
            return NAN
        if rd == 0:
            return 100.0
        if ru == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + ru / rd)


class STDEV:
    """Population standard deviation over `length` bars (Pine biased=true default)."""
    def __init__(self, length: int):
        self.n = max(1, int(length))
        self.buf: deque = deque(maxlen=self.n)

    def update(self, v: float) -> float:
        self.buf.append(v)
        if len(self.buf) < self.n:
            return NAN
        s = 0.0
        for x in self.buf:
            if na(x):
                return NAN
            s += x
        m = s / self.n
        ss = 0.0
        for x in self.buf:
            d = x - m
            ss += d * d
        return math.sqrt(ss / self.n)


class HIGHEST:
    def __init__(self, length: int):
        self.n = max(1, int(length))
        self.buf: deque = deque(maxlen=self.n)

    def update(self, v: float) -> float:
        self.buf.append(v)
        best = NAN
        for x in self.buf:
            if not na(x) and (na(best) or x > best):
                best = x
        return best


class LOWEST(HIGHEST):
    def update(self, v: float) -> float:
        self.buf.append(v)
        best = NAN
        for x in self.buf:
            if not na(x) and (na(best) or x < best):
                best = x
        return best


class PIVOT:
    """ta.pivothigh / ta.pivotlow(src, left, right). Returns src[right] on the bar the
    pivot is confirmed (right bars after it), else na."""
    def __init__(self, left: int, right: int, high: bool = True):
        self.left, self.right, self.high = int(left), int(right), high
        self.buf: deque = deque(maxlen=self.left + self.right + 1)

    def update(self, v: float) -> float:
        self.buf.append(v)
        if len(self.buf) < self.buf.maxlen:
            return NAN
        vals = list(self.buf)
        cand = vals[self.left]                 # src[right] in Pine indexing
        if na(cand):
            return NAN
        for i, x in enumerate(vals):
            if i == self.left or na(x):
                continue
            if self.high and x > cand:
                return NAN
            if (not self.high) and x < cand:
                return NAN
        return cand


class CHANGE:
    def __init__(self):
        self.prev = NAN

    def update(self, v: float) -> float:
        out = NAN if (na(self.prev) or na(v)) else v - self.prev
        self.prev = v
        return out


class BARSSINCE:
    def __init__(self):
        self.count = NAN

    def update(self, cond: bool) -> float:
        if cond:
            self.count = 0
        elif not na(self.count):
            self.count += 1
        return self.count


class PERCENTRANK:
    """% of the previous `length` values that are <= the current value."""
    def __init__(self, length: int):
        self.n = max(1, int(length))
        self.buf: deque = deque(maxlen=self.n + 1)

    def update(self, v: float) -> float:
        self.buf.append(v)
        if len(self.buf) < self.n + 1 or na(v):
            return NAN
        cnt = 0
        vals = list(self.buf)
        for x in vals[:-1]:
            if na(x):
                return NAN
            if x <= v:
                cnt += 1
        return cnt / self.n * 100.0


class VWAP:
    """Session-anchored VWAP (Pine ta.vwap): sum(src*vol)/sum(vol) since the session started."""
    def __init__(self):
        self.pv = 0.0
        self.v = 0.0

    def update(self, src: float, vol: float, new_session: bool) -> float:
        if new_session:
            self.pv, self.v = 0.0, 0.0
        if na(src) or na(vol):
            return NAN
        self.pv += src * vol
        self.v += vol
        return self.pv / self.v if self.v > 0 else NAN


class SUPERTREND:
    """Pine ta.supertrend(factor, atrPeriod) -> (supertrend, direction); direction -1 = up-trend."""
    def __init__(self, factor: float, atr_period: int):
        self.f = float(factor)
        self.atr = ATR(atr_period)
        self.prev_lower = NAN
        self.prev_upper = NAN
        self.prev_st = NAN
        self.prev_close = NAN
        self.prev_atr = NAN

    def update(self, h: float, l: float, c: float):
        atr = self.atr.update(h, l, c)
        src = (h + l) / 2.0
        upper = src + self.f * atr
        lower = src - self.f * atr
        prev_lower = nz(self.prev_lower)
        prev_upper = nz(self.prev_upper)
        c1 = self.prev_close
        if na(lower):
            lower_b = NAN
        else:
            lower_b = lower if (lower > prev_lower or (not na(c1) and c1 < prev_lower)) else prev_lower
        if na(upper):
            upper_b = NAN
        else:
            upper_b = upper if (upper < prev_upper or (not na(c1) and c1 > prev_upper)) else prev_upper
        if na(self.prev_atr):
            direction = 1
        elif self.prev_st == prev_upper:
            direction = -1 if (not na(upper_b) and c > upper_b) else 1
        else:
            direction = 1 if (not na(lower_b) and c < lower_b) else -1
        st = lower_b if direction == -1 else upper_b
        self.prev_lower, self.prev_upper, self.prev_st = lower_b, upper_b, st
        self.prev_close, self.prev_atr = c, atr
        return st, direction
