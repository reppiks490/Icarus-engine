"""Configuration: one strategy, four skins.

Icarus is a single system. Nothing below changes *what* the engine looks for --
a liquidity sweep that fails, confirmed by order flow and structure, inside a
tradable volatility regime. The profiles only re-scale the system's senses to
the microstructure of each venue: tick size, cost, session shape, how noisy the
tape is, and how much weight the sentiment overlay has earned there.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import time
from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "equity"
    FUTURES = "futures"
    MICRO_FUTURES = "micro_futures"     # MNQ / MES / MGC -- retail-sized contracts
    FOREX = "forex"
    CRYPTO = "crypto"


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """A tradable window expressed in the profile's timezone."""

    start: time
    end: time
    label: str = ""

    def contains(self, moment: time) -> bool:
        if self.start <= self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end   # window wraps midnight


@dataclass(frozen=True, slots=True)
class CostModel:
    """Round-turn friction. Costs are modelled in price units, not hand-waved."""

    tick_size: float = 0.01
    spread_ticks: float = 1.0          # quoted half-spread crossed on entry AND exit
    slippage_ticks: float = 0.5        # baseline adverse fill at normal volatility
    slippage_vol_scalar: float = 1.5   # extra slippage as ATR percentile -> 1.0
    commission_per_unit: float = 0.0   # currency per unit of size, per side

    def entry_cost(self, atr_percentile: float) -> float:
        """Price-unit cost of crossing the spread, scaled by the vol regime."""
        ticks = self.spread_ticks + self.slippage_ticks * (1.0 + self.slippage_vol_scalar * atr_percentile)
        return ticks * self.tick_size


@dataclass(frozen=True, slots=True)
class ConfluenceWeights:
    """Weights of the soft confirmation layers. Normalised at scoring time."""

    sweep_quality: float = 1.00        # how cleanly the liquidity pool was raided and rejected
    order_flow: float = 0.95           # delta flip / absorption against the sweep
    structure: float = 0.85            # micro BOS or CHoCH in the trade direction
    volatility: float = 0.55           # regime fitness: expansion out of compression
    location: float = 0.70             # distance from VWAP / value, premium-discount
    momentum: float = 0.45             # higher-timeframe pressure alignment
    sentiment: float = 0.30            # external bias overlay (scales, never flips)
    ml: float = 0.00                   # model vote (XGBoost et al). 0.0 == no model attached

    def as_dict(self) -> dict[str, float]:
        return {
            "sweep_quality": self.sweep_quality,
            "order_flow": self.order_flow,
            "structure": self.structure,
            "volatility": self.volatility,
            "location": self.location,
            "momentum": self.momentum,
            "sentiment": self.sentiment,
            "ml": self.ml,
        }


@dataclass(frozen=True, slots=True)
class Profile:
    """Per-asset-class calibration of the one master system."""

    asset_class: AssetClass
    timezone: str = "UTC"
    point_value: float = 1.0          # currency per 1.0 price unit per contract
    base_timeframe_min: int = 5       # the bar size these bar-count fields assume
    sessions: tuple[SessionWindow, ...] = ()       # empty tuple == trade around the clock
    flat_before_session_end_min: int = 10          # forced flatten ahead of the close
    costs: CostModel = field(default_factory=CostModel)
    weights: ConfluenceWeights = field(default_factory=ConfluenceWeights)

    # --- Volatility gate ------------------------------------------------
    atr_period: int = 14
    atr_regime_lookback: int = 240                 # bars used to rank current ATR
    min_atr_percentile: float = 0.20               # dead tape -> stand down
    max_atr_percentile: float = 0.97               # shock tape -> stand down
    min_atr_to_cost_ratio: float = 6.0             # edge must dwarf friction

    # --- Structure ------------------------------------------------------
    swing_strength: int = 2                        # fractal pivot left/right bars
    structure_lookback: int = 60

    # --- Liquidity ------------------------------------------------------
    equal_level_tolerance_atr: float = 0.12        # clustering tolerance for equal highs/lows
    sweep_min_penetration_atr: float = 0.05        # must genuinely trade through the pool
    sweep_max_penetration_atr: float = 1.30        # beyond this it is a breakout, not a raid
    sweep_reclaim_bars: int = 3                    # bars allowed to reclaim the level

    # --- Order flow -----------------------------------------------------
    cvd_fast: int = 12
    cvd_slow: int = 48
    absorption_lookback: int = 20

    # --- Entry / risk ---------------------------------------------------
    min_confluence: float = 0.58                   # gate on the composite score
    risk_per_trade: float = 0.0050                 # 0.50% of equity at the stop
    max_risk_per_trade: float = 0.0100
    stop_buffer_atr: float = 0.35                  # stop parked beyond the sweep extreme
    first_target_r: float = 1.0
    runner_target_r: float = 2.6
    scale_out_fraction: float = 0.55               # taken at the first target
    breakeven_at_r: float = 1.0
    trail_atr_mult: float = 1.6
    time_stop_bars: int = 36                       # idea decays if it does not work
    exit_policy: str = "pulse"                     # pulse | suite | hybrid (see icarus/exits.py)
    max_concurrent_positions: int = 1              # one cohesive system, one sniper shot
    daily_loss_limit_r: float = 3.0
    consecutive_loss_throttle: int = 3             # halve risk after this many losses
    cooldown_bars_after_exit: int = 2

    def with_overrides(self, **kwargs) -> "Profile":
        """Return a copy with selected fields replaced (used by the optimiser)."""
        return replace(self, **kwargs)


# --------------------------------------------------------------------------
# Calibrations
# --------------------------------------------------------------------------

_US_RTH = (
    SessionWindow(time(9, 30), time(11, 30), "am-drive"),
    SessionWindow(time(13, 30), time(15, 55), "pm-drive"),
)

PROFILES: dict[AssetClass, Profile] = {
    # Equities: opening drive and the afternoon trend leg. Lunch is noise.
    AssetClass.EQUITY: Profile(
        asset_class=AssetClass.EQUITY,
        timezone="America/New_York",
        sessions=_US_RTH,
        costs=CostModel(tick_size=0.01, spread_ticks=1.0, slippage_ticks=1.0, commission_per_unit=0.005),
        weights=ConfluenceWeights(sentiment=0.35),
        min_atr_percentile=0.25,
        risk_per_trade=0.0050,
    ),
    # Futures: deepest book, tightest structure, cheapest friction -> most aggressive gates.
    AssetClass.FUTURES: Profile(
        asset_class=AssetClass.FUTURES,
        timezone="America/New_York",
        sessions=(
            SessionWindow(time(3, 0), time(5, 0), "london-overlap"),
            SessionWindow(time(9, 30), time(11, 30), "am-drive"),
            SessionWindow(time(13, 30), time(15, 55), "pm-drive"),
        ),
        costs=CostModel(tick_size=0.25, spread_ticks=1.0, slippage_ticks=0.5, commission_per_unit=2.25),
        weights=ConfluenceWeights(order_flow=1.10, sentiment=0.20),
        min_atr_percentile=0.20,
        min_confluence=0.56,
        risk_per_trade=0.0060,
    ),
    # FX: 24/5, thin outside killzones, no true volume -> order flow leans on proxies.
    AssetClass.FOREX: Profile(
        asset_class=AssetClass.FOREX,
        timezone="UTC",
        sessions=(
            SessionWindow(time(7, 0), time(10, 0), "london"),
            SessionWindow(time(12, 30), time(16, 0), "new-york"),
        ),
        flat_before_session_end_min=15,
        costs=CostModel(tick_size=0.00001, spread_ticks=2.0, slippage_ticks=1.5,
                        commission_per_unit=0.000035),
        weights=ConfluenceWeights(order_flow=0.70, structure=1.00, location=0.80, sentiment=0.35),
        min_atr_percentile=0.28,
        min_atr_to_cost_ratio=4.0,
        min_confluence=0.62,
        risk_per_trade=0.0040,
    ),
    # Crypto: 24/7, fat tails, funding-driven sentiment, real aggressor data.
    AssetClass.CRYPTO: Profile(
        asset_class=AssetClass.CRYPTO,
        timezone="UTC",
        sessions=(),
        flat_before_session_end_min=0,
        costs=CostModel(tick_size=0.01, spread_ticks=2.0, slippage_ticks=2.0, slippage_vol_scalar=2.5,
                        commission_per_unit=0.0),
        weights=ConfluenceWeights(sweep_quality=1.15, order_flow=1.05, volatility=0.65, sentiment=0.45),
        atr_regime_lookback=288,
        min_atr_percentile=0.22,
        max_atr_percentile=0.95,
        sweep_max_penetration_atr=1.60,
        min_confluence=0.60,
        risk_per_trade=0.0040,
        trail_atr_mult=2.0,
        time_stop_bars=48,
    ),
}


# Micro E-mini Nasdaq-100 (MNQ1!), calibrated bar-for-bar from ICARUS PROTO
# SUITE 01 running on the 10-minute chart: $2/point, 0.25 tick, 05:30-15:30 ET,
# ATR 25, cooldown 15 bars, and the Suite's structure-anchored exit model.
PROFILES[AssetClass.MICRO_FUTURES] = Profile(
    asset_class=AssetClass.MICRO_FUTURES,
    timezone="America/New_York",
    point_value=2.0,                                # MNQ: $2 per index point
    base_timeframe_min=10,
    sessions=(SessionWindow(time(5, 30), time(15, 30), "suite-rth"),),
    flat_before_session_end_min=10,
    # MNQ books ~0.25-0.50 wide; slippage climbs hard on an index in expansion.
    costs=CostModel(tick_size=0.25, spread_ticks=1.0, slippage_ticks=1.0,
                    slippage_vol_scalar=2.0, commission_per_unit=0.37),
    weights=ConfluenceWeights(order_flow=1.05, structure=0.95, sentiment=0.25),
    atr_period=25,                                  # Suite: ATR Length 25
    atr_regime_lookback=240,
    min_atr_percentile=0.20,
    max_atr_percentile=0.97,
    min_atr_to_cost_ratio=6.0,
    swing_strength=3,                               # Suite: Structure Pivot Length 3
    structure_lookback=60,
    sweep_min_penetration_atr=0.05,
    sweep_max_penetration_atr=1.30,
    sweep_reclaim_bars=3,
    min_confluence=0.56,
    risk_per_trade=0.0060,
    exit_policy="hybrid",                           # the whole point of the rebuild
    stop_buffer_atr=0.35,
    first_target_r=1.5,
    runner_target_r=3.0,
    scale_out_fraction=0.40,
    trail_atr_mult=1.5,
    time_stop_bars=24,                              # 4 hours on a 10m chart
    cooldown_bars_after_exit=15,                    # Suite: Cooldown Bars 15
    daily_loss_limit_r=3.0,
)


def profile_for(asset_class: AssetClass | str) -> Profile:
    """Fetch the calibration for an asset class."""
    key = AssetClass(asset_class) if not isinstance(asset_class, AssetClass) else asset_class
    return PROFILES[key]
