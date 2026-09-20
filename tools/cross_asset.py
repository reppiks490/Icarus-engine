"""Cross-asset context, aligned causally to the MNQ tape.

Re-cutting MNQ's own bars cannot create information -- every feature derived
from them is a transform of what the engine already sees. Another instrument's
tape is different: NVDA's print at 09:47 is not in MNQ's bars, so it can carry
signal the engine has no other way to know.

That only holds if the alignment is honest. A bar closing at T may see a
cross-asset bar only if that bar also closed at or before T. The vendor stamps
each bar with its START, so the close is stamp + interval, and a naive join on
the stamp leaks up to one interval of the future into every feature. That is
the single easiest way to manufacture an edge that cannot be traded, so the
shift is done once here and asserted in tests.

Nothing in this module decides anything. It produces a series the confluence
layer can score, and `spread_test` measures whether a series carries any
information at all before it earns that right.
"""

from __future__ import annotations

import glob
import json
import math
import statistics as st
from bisect import bisect_right
from dataclasses import dataclass

SPILL_GLOB = "/root/.claude/projects/*/*/tool-results/mcp-Massive-call_api-*.txt"


@dataclass(slots=True)
class Series:
    """One instrument's closes, indexed by bar CLOSE time in epoch seconds."""

    name: str
    closes: list[float]
    times: list[int]          # bar close, epoch seconds, ascending

    def at(self, ts: int) -> float | None:
        """The last close available at or before `ts`. Never peeks."""
        i = bisect_right(self.times, ts)
        return self.closes[i - 1] if i else None

    def ret(self, ts: int, lookback: int) -> float | None:
        """Log return over `lookback` seconds, ending at the last closed bar."""
        now = self.at(ts)
        then = self.at(ts - lookback)
        if now is None or then is None or then <= 0 or now <= 0:
            return None
        return math.log(now / then)


def _infer_interval(stamps_ms: list[int]) -> int:
    """Bar length in seconds, taken as the modal gap between consecutive stamps.

    Inferred rather than passed in because the spill directory accumulates pulls
    at different resolutions, and using one file's interval to shift another's
    stamps would put the causal boundary in the wrong place.
    """
    if len(stamps_ms) < 3:
        return 300
    gaps: dict[int, int] = {}
    for a, b in zip(stamps_ms, stamps_ms[1:]):
        gap = (b - a) // 1000
        if 0 < gap <= 86400:
            gaps[gap] = gaps.get(gap, 0) + 1
    return max(gaps.items(), key=lambda kv: kv[1])[0] if gaps else 300


def load_series() -> dict[str, Series]:
    """Read every spilled equity/index response into close-time-indexed series.

    Futures spills are skipped: they carry a different header and are already
    handled by build_mnq.py.
    """
    rows: dict[str, dict[int, float]] = {}
    for path in sorted(glob.glob(SPILL_GLOB)):
        try:
            payload = json.load(open(path, encoding="utf-8"))["result"]
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            continue
        lines = payload.strip().split("\n")
        header = lines[0].split(",")
        if header[0] == "ticker":
            continue                                   # futures, handled elsewhere
        if "t" not in header or "c" not in header:
            continue
        name = _name_for(path, payload)
        t_i, c_i = header.index("t"), header.index("c")
        parsed = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) <= max(t_i, c_i):
                continue
            try:
                parsed.append((int(float(parts[t_i])), float(parts[c_i])))
            except ValueError:
                continue
        if not parsed:
            continue
        interval = _infer_interval([t for t, _ in parsed])
        bucket = rows.setdefault(name, {})
        for start_ms, close in parsed:
            # The stamp is the bar's START. Its close is one interval later,
            # and only then may anything downstream see it.
            bucket[start_ms // 1000 + interval] = close

    out = {}
    for name, bucket in rows.items():
        times = sorted(bucket)
        out[name] = Series(name, [bucket[t] for t in times], times)
    return out


_KNOWN = ("QQQ", "NVDA", "TLT", "SPY", "AAPL", "MSFT", "I:NDX", "I:SPX")


def _name_for(path: str, payload: str) -> str:
    """Recover the instrument from the request path recorded alongside the data."""
    for ticker in _KNOWN:
        if f"/{ticker}/" in payload or f"ticker/{ticker}" in payload:
            return ticker
    # The response body carries no ticker for these endpoints, so fall back to
    # the shape of the data: an index feed has no volume column.
    head = payload.strip().split("\n")[0]
    return "I:NDX" if head == "o,c,h,l,t" else f"unknown:{path[-18:-4]}"


def spread_test(bars, series: dict[str, Series], horizon_bars: int = 12) -> dict:
    """Does a feature carry information about MNQ's next `horizon_bars`?

    Terciles rather than a correlation, because the confluence layer consumes a
    bounded score and a monotone-but-nonlinear relationship is exactly what it
    is built to use. The reported number is (top tercile mean forward return)
    minus (bottom tercile mean), in MNQ points.
    """
    features: dict[str, list[tuple[float, float]]] = {}
    for i, bar in enumerate(bars[:-horizon_bars]):
        ts = int(bar.ts.timestamp())
        forward = bars[i + horizon_bars].close - bar.close
        for name, value in _features(ts, series).items():
            if value is not None:
                features.setdefault(name, []).append((value, forward))

    out = {}
    for name, pairs in features.items():
        if len(pairs) < 200:
            continue
        pairs.sort(key=lambda p: p[0])
        cut = len(pairs) // 3
        low = st.fmean([f for _, f in pairs[:cut]])
        high = st.fmean([f for _, f in pairs[-cut:]])
        out[name] = {"n": len(pairs), "spread": high - low, "low": low, "high": high}
    return out


def _features(ts: int, series: dict[str, Series]) -> dict[str, float | None]:
    """Every cross-asset read available at `ts`, all causal."""
    qqq, nvda, tlt, ndx = (series.get(k) for k in ("QQQ", "NVDA", "TLT", "I:NDX"))
    feats: dict[str, float | None] = {}

    for label, s, window in (("qqq_20m", qqq, 1200), ("qqq_1h", qqq, 3600),
                             ("nvda_20m", nvda, 1200), ("nvda_1h", nvda, 3600),
                             ("tlt_1h", tlt, 3600), ("ndx_20m", ndx, 1200)):
        feats[label] = s.ret(ts, window) if s else None

    # Breadth: is the heaviest weight confirming the index, or diverging from it?
    if feats["nvda_20m"] is not None and feats["qqq_20m"] is not None:
        feats["breadth_gap"] = feats["nvda_20m"] - feats["qqq_20m"]

    # Risk appetite: equities up while bonds fall is risk-on in its cleanest form.
    if feats["qqq_1h"] is not None and feats["tlt_1h"] is not None:
        feats["risk_on"] = feats["qqq_1h"] - feats["tlt_1h"]

    # Realised volatility, standing in for the VIX this plan cannot reach.
    if qqq is not None:
        recent = [qqq.ret(ts - k * 300, 300) for k in range(12)]
        recent = [r for r in recent if r is not None]
        if len(recent) >= 8:
            feats["rvol_1h"] = st.pstdev(recent)
    return feats
