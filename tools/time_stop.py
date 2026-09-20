"""Time stops as a real, implementable input -- not a post-hoc slice.

Bucketing finished trades by how long they lasted showed win rate climbing
from 28% to 88% with hold length, flipping at ~32 bars on every timeframe.
That is close to a tautology: a trade survives to 64 bars BECAUSE it never hit
its stop, so the long bands are pre-selected winners and the short bands are
where the losers were sent. The table cannot tell "long holds win" apart from
"holding longer causes winning".

These two rules can, because they change behaviour rather than filter outcomes,
and both are things a live chart can actually do:

  MIN hold  the target is withheld until the trade is `min_hold` bars old. The
            protective stop stays live the whole time -- a time rule that also
            removes the stop is not a time stop, it is unlimited risk. If
            duration causes the edge, forcing trades to stay in should help.
            If the bands were selection, this should hurt, because the losers
            that used to scratch out early now run to a full stop.

  MAX hold  flat at `max_hold` bars regardless. If the edge really lives in the
            long tail, cutting the tail should cost in proportion.

Under Pine semantics an exit order is placed once and lives until filled, so
withholding a target means re-issuing the order later with the limit restored;
that is what `_Deferred` tracks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class TimeStopStats:
    """Proof the rule did something. A silently inert patch reads as 'no effect'."""

    deferred_targets: int = 0
    restored_targets: int = 0
    forced_closes: int = 0

    def __bool__(self) -> bool:
        return bool(self.deferred_targets or self.forced_closes)


class TimeStop:
    """Wraps an Emulator so exits obey a minimum and/or maximum hold."""

    def __init__(self, emulator, *, min_hold: int = 0, max_hold: int = 0) -> None:
        self.em = emulator
        self.min_hold = int(min_hold)
        self.max_hold = int(max_hold)
        self.stats = TimeStopStats()
        self._bar = 0
        self._deferred: dict[str, dict[str, Any]] = {}
        self._real_exit: Callable = emulator.exit
        if self.min_hold:
            emulator.exit = self._exit

    # -- entry age ---------------------------------------------------------
    def _entry_bar(self, entry_id: str) -> int | None:
        bars = [t.entry_bar for t in self.em.open if t.entry_id == entry_id]
        return min(bars) if bars else None

    def _exit(self, id: str, from_entry: str, **kw):
        """Hold back the profit target while the trade is too young."""
        entry_bar = self._entry_bar(from_entry)
        if entry_bar is not None and self._bar - entry_bar < self.min_hold:
            if kw.get("limit") is not None or kw.get("profit") is not None:
                self._deferred[id] = {"from_entry": from_entry, "entry_bar": entry_bar, "kw": dict(kw)}
                self.stats.deferred_targets += 1
                kw = dict(kw)
                kw["limit"] = None
                kw["profit"] = None
        return self._real_exit(id, from_entry, **kw)

    def on_bar(self, bar_index: int) -> None:
        """Call once per bar, after `process_bar` and before the strategy runs."""
        self._bar = bar_index

        # Restore any target whose trade has now served its minimum.
        if self._deferred:
            for exit_id in [k for k, v in self._deferred.items()
                            if bar_index - v["entry_bar"] >= self.min_hold]:
                record = self._deferred.pop(exit_id)
                if self.em.qty_open(record["from_entry"]) > 0:
                    self._real_exit(exit_id, record["from_entry"], **record["kw"])
                    self.stats.restored_targets += 1

        if self.max_hold:
            stale = {t.entry_id for t in self.em.open
                     if bar_index - t.entry_bar >= self.max_hold}
            for entry_id in stale:
                self.em.close(entry_id, "TIME")
                self.stats.forced_closes += 1
