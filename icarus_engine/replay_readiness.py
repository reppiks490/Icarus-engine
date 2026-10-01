"""Evidence-only replay source coverage checks.

A configured/requested timeframe is replayable only when the frozen source contains
observations whose native granularity can actually build that timeframe over the
scored window. Merely having a TFChain object is not evidence that its historical
series was populated.

This module never mutates strategy/order state and never authorizes execution.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


def source_inventory(raw_subbars: Sequence[Tuple[Any, int]], deep: Mapping[int, Sequence[Tuple[Any, int]]]) -> Dict[str, Any]:
    raw: Dict[int, Dict[str, Any]] = {}
    for bar, sub in raw_subbars:
        sub = int(sub); ts = int(bar.ts)
        x = raw.setdefault(sub, {"minutes": sub, "count": 0, "first_ts": ts, "last_ts": ts})
        x["count"] += 1; x["first_ts"] = min(x["first_ts"], ts); x["last_ts"] = max(x["last_ts"], ts)
    deep_out = []
    for target, rows in sorted(deep.items()):
        if not rows:
            continue
        subs = sorted({int(sub) for _, sub in rows})
        times = [int(bar.ts) for bar, _ in rows]
        deep_out.append({"target_minutes": int(target), "source_minutes": subs, "count": len(rows),
                         "first_ts": min(times), "last_ts": max(times)})
    return {"raw_series": [raw[k] for k in sorted(raw)], "deep_series": deep_out,
            "stores_execution_state": False, "execution_authorized": False}


def assess_requested_timeframes(raw_subbars: Sequence[Tuple[Any, int]],
                                deep: Mapping[int, Sequence[Tuple[Any, int]]],
                                requested: Iterable[int], *, chart_minutes: int,
                                window_start: Optional[int] = None,
                                window_end: Optional[int] = None,
                                known_timeframes: Optional[Iterable[int]] = None) -> Dict[str, Any]:
    """Assess whether frozen observations can actually build each requested TF.

    Raw observations can build a timeframe only when sub <= tf and tf % sub == 0.
    Deep history is target-specific because the replay path feeds deep[m] only to
    chain m. The check is deliberately conservative: a source that begins after
    or ends before the scored window is blocked rather than silently accepted.
    """
    raw = tuple(raw_subbars or ())
    requested = sorted({int(x) for x in requested})
    known = None if known_timeframes is None else {int(x) for x in known_timeframes}
    inv = source_inventory(raw, deep)
    raw_by_sub = {int(x["minutes"]): x for x in inv["raw_series"]}

    all_ts = [int(bar.ts) for bar, _ in raw]
    if not all_ts:
        for rows in deep.values():
            all_ts.extend(int(bar.ts) for bar, _ in rows)
    source_first = min(all_ts) if all_ts else None
    source_last = max(all_ts) if all_ts else None
    start = int(window_start) if window_start is not None else source_first
    end = int(window_end) if window_end is not None else source_last

    rows = []
    blocked = []
    for minutes in requested:
        compatible = sorted(sub for sub in raw_by_sub if sub <= minutes and minutes % sub == 0)
        firsts = [raw_by_sub[sub]["first_ts"] for sub in compatible]
        lasts = [raw_by_sub[sub]["last_ts"] for sub in compatible]
        counts = sum(int(raw_by_sub[sub]["count"]) for sub in compatible)

        direct = tuple(deep.get(minutes) or ())
        deep_source_minutes = sorted({int(sub) for _, sub in direct})
        if direct:
            dts = [int(bar.ts) for bar, _ in direct]
            firsts.append(min(dts)); lasts.append(max(dts)); counts += len(direct)

        first = min(firsts) if firsts else None
        last = max(lasts) if lasts else None
        reasons = []
        if first is None:
            reasons.append("NO_COMPATIBLE_SUBBARS")
        else:
            if start is not None and first > start:
                reasons.append("STARTS_AFTER_WINDOW")
            tolerance = max(int(chart_minutes), minutes) * 60
            if end is not None and last + tolerance < end:
                reasons.append("ENDS_BEFORE_WINDOW")
            # A new chain absent from the frozen runner needs enough source span
            # to materialize at least one completed bucket. Existing chains keep
            # backward-compatible replay semantics for tiny diagnostic fixtures,
            # but chain existence alone never rescues incompatible granularity.
            if known is not None and minutes not in known:
                smallest = min(compatible) if compatible else None
                span = (last - first + smallest * 60) if smallest is not None else 0
                if span < minutes * 60:
                    reasons.append("INSUFFICIENT_SPAN_FOR_NEW_TIMEFRAME")
        status = "BLOCKED" if reasons else "READY"
        if reasons:
            blocked.append(minutes)
        rows.append({"minutes": minutes, "status": status, "reasons": reasons,
                     "raw_source_minutes": compatible, "deep_source_minutes": deep_source_minutes,
                     "observations": counts, "first_ts": first, "last_ts": last})

    return {"status": "BLOCKED" if blocked else "READY", "requested_minutes": requested,
            "blocked_minutes": blocked, "window_start": start, "window_end": end,
            "source_first_ts": source_first, "source_last_ts": source_last,
            "timeframes": rows, "inventory": inv,
            "meaning": "REPLAY_SOURCE_COVERAGE_ONLY",
            "execution_authorized": False, "trading_execution_authorized": False}


def blocked_message(symbol: str, assessment: Mapping[str, Any]) -> str:
    bad = assessment.get("blocked_minutes") or []
    details = []
    for row in assessment.get("timeframes") or []:
        if row.get("status") != "READY":
            details.append(f"{row.get('minutes')}m:{'+'.join(row.get('reasons') or ['UNKNOWN'])}")
    available = [f"{x['minutes']}m" for x in (assessment.get("inventory") or {}).get("raw_series", [])]
    return (f"{symbol}: cached history unavailable for requested replay timeframe coverage {bad}; "
            f"{', '.join(details)}; cached raw granularities {available or ['none']}. "
            "Fetch compatible lower-timeframe history for the scored window before claiming replay/parity evidence.")
