"""Liquidity mapping and sweep detection -- the trigger layer of Icarus.

The premise: resting stop orders cluster in obvious places (prior session
extremes, swing pivots, equal highs/lows, the session open). Price is drawn to
those pools, fills the resting liquidity, and -- when the move was a raid
rather than a trend leg -- immediately reclaims the level. That failure is the
entry trigger. Everything else in the engine exists to confirm or veto it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Deque, Iterable

from icarus.data import Bar
from icarus.features.structure import Swing, SwingType


class PoolKind(str, Enum):
    PRIOR_SESSION_HIGH = "prior_session_high"
    PRIOR_SESSION_LOW = "prior_session_low"
    SESSION_HIGH = "session_high"
    SESSION_LOW = "session_low"
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    SESSION_OPEN = "session_open"


# Relative weight of each pool type: how much resting size we believe sits there.
_POOL_WEIGHT = {
    PoolKind.PRIOR_SESSION_HIGH: 1.00,
    PoolKind.PRIOR_SESSION_LOW: 1.00,
    PoolKind.EQUAL_HIGHS: 0.95,
    PoolKind.EQUAL_LOWS: 0.95,
    PoolKind.SESSION_HIGH: 0.80,
    PoolKind.SESSION_LOW: 0.80,
    PoolKind.SWING_HIGH: 0.65,
    PoolKind.SWING_LOW: 0.65,
    PoolKind.SESSION_OPEN: 0.40,
}

_UPSIDE_KINDS = {
    PoolKind.PRIOR_SESSION_HIGH, PoolKind.SESSION_HIGH,
    PoolKind.SWING_HIGH, PoolKind.EQUAL_HIGHS,
}


@dataclass(slots=True)
class LiquidityPool:
    """A price level believed to hold resting stop orders."""

    level: float
    kind: PoolKind
    created_index: int
    touches: int = 1
    swept: bool = False

    @property
    def side(self) -> int:
        """+1 if the pool sits ABOVE price (buy stops), -1 if below (sell stops)."""
        return 1 if self.kind in _UPSIDE_KINDS else -1

    @property
    def weight(self) -> float:
        """Pool conviction: base weight lifted by repeated defence of the level."""
        return _POOL_WEIGHT[self.kind] * min(1.35, 1.0 + 0.12 * (self.touches - 1))


@dataclass(slots=True)
class Sweep:
    """A confirmed liquidity raid that failed and reclaimed the level."""

    ts: datetime
    index: int
    direction: int              # +1 long setup (lows swept), -1 short setup (highs swept)
    pool: LiquidityPool
    extreme: float              # the wick extreme of the raid -- the stop reference
    penetration_atr: float
    reclaim_bars: int
    rejection: float            # rejection wick as a fraction of the raid bar's range
    quality: float              # composite [0, 1]

    @property
    def level(self) -> float:
        return self.pool.level


@dataclass(slots=True)
class _Pending:
    """A pool that has been penetrated and is waiting for a reclaim (or not)."""

    pool: LiquidityPool
    start_index: int
    extreme: float
    penetration_atr: float
    rejection: float


class LiquidityMap:
    """Maintains the live map of liquidity pools and emits confirmed sweeps."""

    __slots__ = (
        "tolerance_atr", "min_penetration_atr", "max_penetration_atr", "reclaim_bars",
        "max_pools", "_pools", "_pending", "_index", "session_high", "session_low",
        "session_open", "prior_session_high", "prior_session_low", "last_sweep",
        "_tolerance",
    )

    def __init__(
        self,
        tolerance_atr: float = 0.12,
        min_penetration_atr: float = 0.05,
        max_penetration_atr: float = 1.30,
        reclaim_bars: int = 3,
        max_pools: int = 48,
    ) -> None:
        self.tolerance_atr = tolerance_atr
        self.min_penetration_atr = min_penetration_atr
        self.max_penetration_atr = max_penetration_atr
        self.reclaim_bars = reclaim_bars
        self.max_pools = max_pools
        self._pools: Deque[LiquidityPool] = deque(maxlen=max_pools)
        self._pending: list[_Pending] = []
        self._index = -1
        self._tolerance = 0.0
        self.session_high: float | None = None
        self.session_low: float | None = None
        self.session_open: float | None = None
        self.prior_session_high: float | None = None
        self.prior_session_low: float | None = None
        self.last_sweep: Sweep | None = None

    # ------------------------------------------------------------------
    # Session bookkeeping
    # ------------------------------------------------------------------
    def roll_session(self, opening_bar: Bar) -> None:
        """Close the current session's books and open a new one.

        Yesterday's extremes become today's primary pools: they are the levels
        every desk can see, so they are where the stops are.
        """
        if self.session_high is not None and self.session_low is not None:
            self.prior_session_high = self.session_high
            self.prior_session_low = self.session_low
            self._register(self.prior_session_high, PoolKind.PRIOR_SESSION_HIGH)
            self._register(self.prior_session_low, PoolKind.PRIOR_SESSION_LOW)
        self.session_open = opening_bar.open
        self.session_high = opening_bar.high
        self.session_low = opening_bar.low
        self._register(self.session_open, PoolKind.SESSION_OPEN)
        self._pending.clear()

    # ------------------------------------------------------------------
    # Pool maintenance
    # ------------------------------------------------------------------
    def _register(self, level: float, kind: PoolKind) -> LiquidityPool:
        """Add a pool, merging into an existing one at the same price level."""
        tolerance = self._tolerance
        for pool in self._pools:
            if pool.kind is kind and abs(pool.level - level) <= tolerance:
                pool.touches += 1
                pool.swept = False
                return pool
        pool = LiquidityPool(level=level, kind=kind, created_index=self._index)
        self._pools.append(pool)
        return pool

    def ingest_swings(self, swings: Iterable[Swing]) -> None:
        """Promote newly confirmed pivots into pools, clustering equal levels."""
        for swing in swings:
            if swing.kind is SwingType.HIGH:
                pool = self._register(swing.price, PoolKind.SWING_HIGH)
                if pool.touches >= 2:
                    self._register(pool.level, PoolKind.EQUAL_HIGHS)
            else:
                pool = self._register(swing.price, PoolKind.SWING_LOW)
                if pool.touches >= 2:
                    self._register(pool.level, PoolKind.EQUAL_LOWS)

    def update(self, bar: Bar, atr: float) -> Sweep | None:
        """Advance one bar. Returns a confirmed sweep, if one completed here."""
        self._index += 1
        if atr <= 0.0:
            return None
        self._tolerance = self.tolerance_atr * atr   # clustering tolerance, refreshed each bar

        if self.session_high is None:
            self.session_open = bar.open
            self.session_high = bar.high
            self.session_low = bar.low
        else:
            self.session_high = max(self.session_high, bar.high)
            self.session_low = min(self.session_low, bar.low)

        # Open first, then resolve: a single-bar poke-and-reclaim is a complete
        # sweep and must be able to confirm on the bar that produced it.
        self._open_pending(bar, atr)
        confirmed = self._resolve_pending(bar, atr)
        # Running session extremes are pools too, refreshed every bar.
        self._register(self.session_high, PoolKind.SESSION_HIGH)
        self._register(self.session_low, PoolKind.SESSION_LOW)
        if confirmed is not None:
            self.last_sweep = confirmed
        return confirmed

    # ------------------------------------------------------------------
    # Sweep state machine
    # ------------------------------------------------------------------
    def _open_pending(self, bar: Bar, atr: float) -> None:
        """Detect fresh penetrations of untouched pools."""
        for pool in self._pools:
            if pool.swept or pool.created_index >= self._index:
                continue
            if any(item.pool is pool for item in self._pending):
                continue

            if pool.side > 0 and bar.high > pool.level:
                penetration = (bar.high - pool.level) / atr
                if penetration > self.max_penetration_atr:
                    pool.swept = True          # genuine breakout: the pool is consumed
                elif penetration >= self.min_penetration_atr:
                    rejection = bar.upper_wick / bar.range if bar.range > 0 else 0.0
                    self._pending.append(
                        _Pending(pool, self._index, bar.high, penetration, rejection)
                    )
            elif pool.side < 0 and bar.low < pool.level:
                penetration = (pool.level - bar.low) / atr
                if penetration > self.max_penetration_atr:
                    pool.swept = True          # genuine breakout: the pool is consumed
                elif penetration >= self.min_penetration_atr:
                    rejection = bar.lower_wick / bar.range if bar.range > 0 else 0.0
                    self._pending.append(
                        _Pending(pool, self._index, bar.low, penetration, rejection)
                    )

    def _resolve_pending(self, bar: Bar, atr: float) -> Sweep | None:
        """Confirm, extend, or discard pending raids. Best sweep on the bar wins."""
        survivors: list[_Pending] = []
        best: Sweep | None = None

        for item in self._pending:
            age = self._index - item.start_index
            pool = item.pool
            upside = pool.side > 0

            # Track the raid's extreme while it is still in progress.
            if upside:
                if bar.high > item.extreme:
                    item.extreme = bar.high
                    item.penetration_atr = (bar.high - pool.level) / atr
                    item.rejection = max(item.rejection, bar.upper_wick / bar.range if bar.range > 0 else 0.0)
                reclaimed = bar.close < pool.level
                invalidated = item.penetration_atr > self.max_penetration_atr
            else:
                if bar.low < item.extreme:
                    item.extreme = bar.low
                    item.penetration_atr = (pool.level - bar.low) / atr
                    item.rejection = max(item.rejection, bar.lower_wick / bar.range if bar.range > 0 else 0.0)
                reclaimed = bar.close > pool.level
                invalidated = item.penetration_atr > self.max_penetration_atr

            if invalidated:
                pool.swept = True          # it was a genuine break: retire the pool
                continue
            if reclaimed:
                pool.swept = True
                sweep = Sweep(
                    ts=bar.ts,
                    index=self._index,
                    direction=-1 if upside else 1,
                    pool=pool,
                    extreme=item.extreme,
                    penetration_atr=item.penetration_atr,
                    reclaim_bars=age,
                    rejection=item.rejection,
                    quality=self._quality(item, age),
                )
                if best is None or sweep.quality > best.quality:
                    best = sweep
                continue
            if age >= self.reclaim_bars:
                pool.swept = True          # accepted beyond the level -> no raid
                continue
            survivors.append(item)

        self._pending = survivors
        return best

    def _quality(self, item: _Pending, reclaim_age: int) -> float:
        """Score a completed raid in [0, 1].

        Four ingredients, all of them things a desk actually watches:
          1. Penetration depth in the sweet spot -- deep enough to fill stops,
             shallow enough that it was not real acceptance.
          2. Speed of the reclaim -- an instant reclaim is a failed auction.
          3. Rejection wick -- visible evidence of absorption at the extreme.
          4. Pool weight -- how much size we believe was resting there.
        """
        span = max(1e-9, self.max_penetration_atr - self.min_penetration_atr)
        normalised = (item.penetration_atr - self.min_penetration_atr) / span
        # Peak reward around a third of the way into the allowed band.
        depth_score = max(0.0, 1.0 - abs(normalised - 0.33) / 0.67)
        speed_score = 1.0 - min(1.0, reclaim_age / max(1, self.reclaim_bars))
        rejection_score = min(1.0, item.rejection / 0.6)
        pool_score = min(1.0, item.pool.weight / 1.35)

        score = (
            0.32 * depth_score
            + 0.26 * speed_score
            + 0.24 * rejection_score
            + 0.18 * pool_score
        )
        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    def pools(self) -> list[LiquidityPool]:
        return [pool for pool in self._pools if not pool.swept]

    def nearest_pool(self, price: float, side: int) -> LiquidityPool | None:
        """Closest live pool on ``side`` (+1 above price, -1 below) -- the magnet."""
        candidates = [
            pool for pool in self._pools
            if not pool.swept and ((pool.level > price) if side > 0 else (pool.level < price))
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda pool: abs(pool.level - price))
