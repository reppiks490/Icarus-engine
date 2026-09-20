"""Pine Script semantics for Python — `na`, `nz`, history-referencing series.

The port keeps Pine's names and evaluation model: every value is recomputed
once per bar, `x[1]` is the previous bar's value, `var` state persists, and
`na` propagates through arithmetic (Python NaN does the same) while any
comparison against `na` is false (Python NaN does the same).
"""
from __future__ import annotations

import math
from collections import deque
from typing import Iterable, Optional

NAN = float("nan")


def na(x) -> bool:
    return x is None or (isinstance(x, float) and x != x)


def nz(x, d=0.0):
    return d if na(x) else x


def fixnan(prev, x):
    """Pine fixnan: replace na with the last non-na value."""
    return prev if na(x) else x


def pmax(*xs):
    """Pine math.max with na propagation: any na argument -> na.

    This is the reading the script itself assumes everywhere it guards with
    nz()/na() before calling math.max (e.g. `math.max(nz(on_hi_live, _h), _h)`,
    `na(rate_best_price) ? _c : math.max(rate_best_price, _c)`), and it is the
    common Pine idiom (`math.max(nz(x), y)`). A consequence the port reproduces
    faithfully: the script's Kalman filter never leaves its cold start (see
    Inputs.kf_cold_start_fix)."""
    for x in xs:
        if na(x):
            return NAN
    return max(xs)


def pmin(*xs):
    for x in xs:
        if na(x):
            return NAN
    return min(xs)


def clamp(x, lo, hi):
    return pmax(lo, pmin(hi, x))


def pint(x) -> int:
    """Pine int(): truncation toward zero (na → 0 is NOT Pine, but callers guard)."""
    if na(x):
        return 0
    return int(x)


def pround(x) -> float:
    """Pine math.round: half away from zero."""
    if na(x):
        return NAN
    return float(math.floor(x + 0.5)) if x >= 0 else -float(math.floor(-x + 0.5))


class Series:
    """A bar-indexed series. `s[0]` is the current bar, `s[1]` the previous, …
    Values outside the retained window (or before the first push) read as NaN,
    exactly like Pine's history operator on early bars."""
    __slots__ = ("_buf",)

    def __init__(self, maxlen: int = 128, values: Optional[Iterable[float]] = None):
        self._buf: deque = deque(maxlen=maxlen)
        if values:
            self._buf.extend(values)

    def push(self, v) -> None:
        self._buf.append(v)

    def set(self, v) -> None:
        """Reassign the current bar's value (Pine `:=`)."""
        if self._buf:
            self._buf[-1] = v
        else:
            self._buf.append(v)

    def __getitem__(self, i: int):
        n = len(self._buf)
        j = n - 1 - i
        if i < 0 or j < 0:
            return NAN
        return self._buf[j]

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def cur(self):
        return self._buf[-1] if self._buf else NAN

    def window(self, n: int):
        """Last n values oldest→newest (fewer if not available)."""
        buf = self._buf
        k = min(n, len(buf))
        return [buf[len(buf) - k + i] for i in range(k)]
