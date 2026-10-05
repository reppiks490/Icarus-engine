# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.costs: per-contract cost model (commission + fees + slippage)
"""Cost assumptions for 1 contract.

MNQ base: $0.85/side all-in commission+exchange+NFA and 1 tick slippage per side
($2.70 round trip). CL research notes (costs_conventions_data_feeds.md) put a
cited all-in MNQ round trip near $2.50 with slippage assumed, so the base is
slightly conservative. MNQ_STRESS doubles both. Assumption pending
verification from CME/broker fee schedules; never treat as a quote.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    name: str
    tick_size: float
    tick_value: float
    commission_per_side_usd: float
    slippage_ticks_per_side: float

    @property
    def point_value(self) -> float:
        return self.tick_value / self.tick_size

    @property
    def round_trip_points(self) -> float:
        return 2 * self.commission_per_side_usd / self.point_value + 2 * self.slippage_ticks_per_side * self.tick_size

    def trade_cost_points(self, entry_px):
        """Round-trip cost per trade in price points (independent of price for tick-based futures)."""
        import numpy as np
        return np.full(np.shape(entry_px), self.round_trip_points, dtype=float)

    def spec(self) -> dict:
        return dict(name=self.name, tick_size=self.tick_size, tick_value=self.tick_value,
                    commission_per_side_usd=self.commission_per_side_usd,
                    slippage_ticks_per_side=self.slippage_ticks_per_side,
                    round_trip_points=self.round_trip_points,
                    round_trip_usd=self.round_trip_points * self.point_value)


@dataclass(frozen=True)
class PctCostModel:
    """Percentage costs for spot/perpetual crypto: fee + slippage in basis points per side (assumption)."""
    name: str
    fee_bps_per_side: float
    slippage_bps_per_side: float
    point_value: float = 1.0

    def trade_cost_points(self, entry_px):
        import numpy as np
        return np.asarray(entry_px, dtype=float) * 2 * (self.fee_bps_per_side + self.slippage_bps_per_side) / 1e4

    def spec(self) -> dict:
        return dict(name=self.name, fee_bps_per_side=self.fee_bps_per_side,
                    slippage_bps_per_side=self.slippage_bps_per_side,
                    round_trip_bps=2 * (self.fee_bps_per_side + self.slippage_bps_per_side))


MNQ = CostModel("MNQ", 0.25, 0.50, 0.85, 1.0)
MNQ_STRESS = CostModel("MNQ_STRESS", 0.25, 0.50, 1.70, 2.0)
NQ = CostModel("NQ", 0.25, 5.00, 2.50, 1.0)
NQ_STRESS = CostModel("NQ_STRESS", 0.25, 5.00, 5.00, 2.0)  # CL 2026-10-04: doubles both, like MNQ_STRESS
CRYPTO_PERP = PctCostModel("CRYPTO_PERP", 5.0, 1.0)          # ~taker perp fee + 1 bp slippage per side
CRYPTO_PERP_STRESS = PctCostModel("CRYPTO_PERP_STRESS", 10.0, 2.0)
