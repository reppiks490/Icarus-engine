"""Every `input.*` of THE PULSE OF ICARUS v3.1, with the script's own defaults.

Field names are the Pine variable names so the port reads line-for-line
against the script. `crypto_profile()` applies the handful of changes a trader
would make in TradingView's input dialog when loading the script on a 24/7
crypto chart (session/EOD/NQ-calendar logic off, percentage-based exits).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from typing import Dict


@dataclass
class Inputs:
    # §1 TP / SL
    tp1_pts: float = 15.0
    tp2_pts: float = 30.0
    sl_pts: float = 45.0
    # RATE engine
    rate_atr_len: int = 14
    rate_adx_len: int = 14
    rate_adx_smooth: int = 14
    rate_atr_fast: int = 5
    rate_atr_slow: int = 30
    rate_eff_len: int = 30
    rate_min_mult: float = 2.0
    rate_max_mult: float = 5.0
    # FDI / cycle
    fdi_len: int = 30
    fdi_smooth: int = 5
    use_cycle: bool = True
    cycle_smooth: int = 5
    # market profile
    use_mp: bool = True
    mp_atr_div: int = 4
    # sizing
    qty_contracts: int = 5
    point_value: float = 20.0
    # session / filters
    use_session: bool = True
    sess_window: str = "0930-1600"
    use_cooldown: bool = True
    cooldown_bars: int = 3
    use_max_loss: bool = False
    max_daily_loss: float = -5000.0
    # confluence gate
    use_confluence: bool = True
    use_adaptive_weights: bool = True
    use_adaptive_threshold: bool = True
    conf_min_votes: int = 5
    cci_len: int = 10
    # zones
    zone_piv: int = 5
    max_zones_n: int = 5
    zone_min_reac: float = 1.5
    # structure
    use_struct: bool = True
    struct_piv: int = 3
    # liquidity sweeps
    sweep_min_level_age: int = 4
    sweep_min_wick_atr: float = 0.15
    use_sweep: bool = True
    # order blocks
    use_ob: bool = True
    ob_disp_mult: float = 1.4
    ob_max_count: int = 4
    ob_invalidate_atr: float = 0.4
    # premium / discount
    use_premdisc: bool = True
    # SMC enhancement
    use_smc_enhance: bool = True
    smc_enhance_discount: float = 0.90
    smc_confirm_window: int = 5
    # trailing TP2
    use_trailing_tp2: bool = False
    trail_atr_mult: float = 2.5
    trail_kf_buffer_atr: float = 0.3
    use_ltf_trail_tighten: bool = True
    ltf_weak_thresh: float = 0.35
    ltf_tighten_mult: float = 0.55
    # entry timing (v2)
    use_arm_window: bool = True
    arm_bars: int = 3
    arm_max_chase_atr: float = 0.75
    use_entry_window: bool = True
    sess_entry_window: str = "0930-1530"
    use_pullback_entry: bool = False
    pullback_atr: float = 0.35
    pullback_max_bars: int = 3
    pullback_fallback: bool = True
    # runner protection (v3)
    runner_mode: str = "Net-BE → Delayed BE"       # | "Immediate BE (v2)" | "Net-BE only" | "Original SL"
    be_offset_pts: float = 1.0
    be_delay_bars: int = 3
    be_extend_atr: float = 0.5
    runner_weak_be: bool = True
    runner_weak_regime: float = 0.40
    tide_be_after_tp1: bool = True
    # sizing (v3)
    size_mode: str = "Fixed"                        # | "Risk-$ per trade" | "Vol-regime tercile"
    risk_usd_per_trade: float = 1500.0
    vol_rank_bars: int = 500
    vol_low_mult: float = 0.50
    vol_mid_mult: float = 0.75
    # session structure bias (v3)
    use_session_bias: bool = True
    sess_bias_weight: float = 0.5
    use_hour_breach: bool = True
    hour_breach_weight: float = 0.5
    # intraday timing (v3)
    midday_mode: str = "Penalize"                   # Off | Penalize | Block
    midday_window: str = "1130-1300"
    use_event_blackout: bool = True
    fomc_dates: str = ("2025-01-29,2025-03-19,2025-05-07,2025-06-18,2025-07-30,2025-09-17,2025-10-29,2025-12-10,"
                       "2026-01-28,2026-03-18,2026-04-29,2026-06-17,2026-07-29,2026-09-16,2026-10-28,2026-12-09")
    fomc_window: str = "1345-1500"
    use_hv_open_block: bool = False
    hv_open_dates: str = ""
    hv_open_window: str = "0930-1000"
    # exit management (v2)
    tp1_split_pct: int = 50
    use_flip_exit: bool = True
    use_eod_flat: bool = True
    eod_flat_hhmm: int = 1555
    eod_flat_tide: bool = False
    # TP/SL mode
    tpsl_mode: str = "Fixed Points"                 # | ATR-Based | Percentage-Based | Structure-Based
    tp1_atr_mult: float = 3.0
    tp2_atr_mult: float = 6.0
    sl_atr_mult: float = 4.5
    tp1_pct: float = 0.12
    tp2_pct: float = 0.24
    sl_pct: float = 0.18
    struct_sl_buffer_atr: float = 0.5
    struct_tp2_ext_mult: float = 1.0
    # Kalman / MAMA
    use_kalman: bool = True
    kf_cold_start_fix: bool = False        # v3.2 patch: re-seed the filter (incl. covariance) until every input is a number
    kf_r_base: float = 0.15
    kf_r_fdi_gain: float = 0.35
    use_adaptive_kf_r: bool = True
    kf_adapt_blend: float = 0.50
    kf_q_base: float = 0.05
    use_pma: bool = True
    mama_fast_lim: float = 0.5
    mama_slow_lim: float = 0.05
    shock_z_thresh: float = 2.5
    shock_decay_bars: int = 8
    shock_boost_mult: float = 1.35
    # permutation entropy
    use_pe: bool = True
    pe_len: int = 30
    use_pe_weighted: bool = True
    pe_na_poison_fix: bool = False         # v3.3 patch: skip the PE block until atr14/_c[3] are numbers (TradingView: pe_norm is stuck at 0)
    pe_thresh: float = 0.75
    pe_trc_fdi: float = 1.35
    pe_trc_hst: float = 0.52
    use_cc: bool = True
    cc_alpha_inp: float = 0.07
    use_div_veto: bool = True
    div_lkb: int = 20
    div_adaptive: bool = True
    dv_sd_mult: float = 0.75
    div_min_count: int = 2
    # HTF / LTF
    htf_tf_1: str = "15"
    htf_tf_2: str = "30"
    htf_tf_3: str = "60"
    htf_tf_4: str = "240"
    htf_tf_5: str = "D"
    htf_min_bull_for_bias: int = 3
    use_ltf_check: bool = True
    ltf_instability_bars: int = 3
    ltf_intrabar: str = "first"            # engine: which intrabar `request.security(LTF, expr[1], lookahead_on)` returns - "first" (TradingView historical bars) | "last" (TradingView realtime bars)
    use_ltf_veto: bool = False
    use_real_ohlc: bool = False
    # rejection cluster (§9.13)
    use_rejection_cluster: bool = True
    rej_min_cluster: int = 2
    rej_cluster_window: int = 3
    rej_min_wick_ratio: float = 0.35
    expansion_confirm_bars: int = 2
    expansion_min_atr: float = 0.6
    use_cisd: bool = True
    fvg_min_size_atr: float = 0.25
    fvg_max_age: int = 120
    # power of three
    use_po3: bool = True
    po3_range_lkb: int = 10
    po3_accum_range_mult: float = 2.0
    po3_accum_regime_max: float = 0.40
    po3_accum_adx_max: float = 20.0
    use_po3_gate_rejection: bool = True
    # TIDE
    use_tide: bool = True
    tide_confirm_bars: int = 2
    tide_confirm_mode: str = "Balanced"             # Strict | Balanced | Loose
    use_tide_poc_target: bool = True
    tide_qty: int = 2
    use_tide_regime_filter: bool = True
    tide_ext_mult: float = 1.0
    # volume delta
    use_vol_delta: bool = True
    vd_lookback: int = 10
    vd_spike_mult: float = 1.5
    # stagnation
    use_stagnation_exit: bool = True
    stagnation_bars: int = 15
    stagnation_min_atr: float = 0.5
    # empirical TP
    use_empirical_tp: bool = False
    emp_window: int = 50
    emp_min_obs: int = 20
    emp_percentile: float = 40.0
    emp_min_pct: float = 0.05
    emp_max_pct: float = 0.50
    use_emp_regime_split: bool = True
    emp_holdout_recent: int = 10
    # time of day
    use_tod_tracking: bool = True
    use_tod_filter: bool = False
    tod_min_sample: int = 12
    tod_min_winrate: float = 0.55
    # family confluence
    use_family_confluence: bool = True
    family_min_for_bonus: int = 4
    family_discount: float = 0.90
    # pulse / conviction sizing
    pulse_conf_weight: float = 0.60
    use_conviction_sizing: bool = False
    conv_min_mult: float = 0.40
    conv_floor: float = 0.35
    conv_ceiling: float = 0.85

    def to_dict(self) -> Dict:
        return asdict(self)


def nq_profile() -> Inputs:
    """The script exactly as shipped (NQ intraday)."""
    return Inputs()


def crypto_profile(price: float = 0.0, mintick: float = 0.01) -> Inputs:
    """What you would change in the input dialog to run the script on a 24/7 crypto chart:
    no RTH gate / entry window / EOD flat, no NQ-calendar priors, exits as % of price,
    and a break-even offset that is a sane tick multiple for the instrument's price."""
    be = max(mintick, round(price * 0.00005, 8)) if price > 0 else mintick
    return replace(Inputs(),
                   use_session=False, use_entry_window=False, use_eod_flat=False,
                   use_session_bias=False, use_hour_breach=False, midday_mode="Off",
                   use_event_blackout=False, use_hv_open_block=False,
                   tpsl_mode="Percentage-Based", be_offset_pts=be)
