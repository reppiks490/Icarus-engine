"""THE PULSE OF ICARUS v3.1 — Python port of the Pine strategy (signal + execution).

The port follows the script top to bottom, section by section, keeping the
Pine variable names so any line can be checked against the source
(`THE_PULSE_OF_ICARUS_v3_1_bridge.txt`, section numbers in comments). Only
visuals (§13) and alerts (§14) are omitted; everything that decides an order
is here. Pine `var` state lives on `self`, per-bar values are locals, series
that are read with `[n]` are `Series` objects pushed once per bar.

Known, documented departures from TradingView (see PARITY.md):
  A1  ta.pivothigh/low: ties count as pivots (reference-manual behaviour is undocumented)
  A2  math.max/min with na -> na (the script's own nz() guards assume this)
  A3  use_real_ohlc: the runtime feeds this class real bars when it is on and the
      chart is Heikin Ashi (runtime.py), so the flag needs no code here
  A4  the three External Macro Context request.security() calls (VIX/DXY/TNX)
      are informational only in the script; not fetched here
  A5  request.security lower-timeframe idiom ([1] + lookahead_on on "2"/"5" from a
      higher chart timeframe) → value of the intrabar before the last intrabar
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..emulator import Emulator
from ..pine.series import NAN, Series, na, nz, pmax, pmin, pround
from ..pine import ta
from ..pine.timeframe import (Bar, in_session, ny_date_str, ny_dayofmonth, ny_hour, ny_hour_minute,
                              ny_minute, utc_date_str)
from .inputs import Inputs


def _log(x: float) -> float:
    return NAN if (na(x) or x <= 0) else math.log(x)


class PulseStrategy:
    def __init__(self, inp: Inputs, em: Emulator, *, mintick: float, tf_minutes: int,
                 session_key: Optional[Callable[[int], str]] = None):
        self.i = inp
        self.em = em
        self.mintick = float(mintick)
        self.tf_minutes = int(tf_minutes)
        self.session_key = session_key or utc_date_str      # VWAP anchor (new trading session)
        self._last_session_key: Optional[str] = None
        i = inp

        # ── series with history ──
        self.c = Series(200); self.o = Series(16); self.h = Series(16); self.l = Series(16); self.vol = Series(16)
        self.sp = Series(8); self.detr = Series(8)
        self.rsi_s = Series(8); self.ftr_s = Series(4)
        self.regime_s = Series(64); self.kfvel_s = Series(64); self.pe_s = Series(64); self.adx_s = Series(8)
        self.phase_s = Series(4); self.cc_s = Series(4); self.uptrend_s = Series(4)

        # ── ta objects (one per Pine call site) ──
        self.dmi = ta.DMI(i.rate_adx_len, i.rate_adx_smooth)
        self.atr_fast = ta.ATR(i.rate_atr_fast); self.atr_slow = ta.ATR(i.rate_atr_slow)
        self.atr_rate = ta.ATR(i.rate_atr_len); self.atr14 = ta.ATR(14)
        self.fdi_ema = ta.EMA(i.fdi_smooth); self.regime_ema = ta.EMA(5); self.hurst_ema = ta.EMA(5)
        self.i1_ema = ta.EMA(i.cycle_smooth); self.q1_ema = ta.EMA(i.cycle_smooth)
        self.avg_vol_sma = ta.SMA(50)
        self.d_hi_lkb = ta.HIGHEST(i.zone_piv + 1); self.s_lo_lkb = ta.LOWEST(i.zone_piv + 1)
        self.ph_piv = ta.PIVOT(i.zone_piv, i.zone_piv, True); self.pl_piv = ta.PIVOT(i.zone_piv, i.zone_piv, False)
        self.rsi = ta.RSI(14); self.ftr_hi = ta.HIGHEST(14); self.ftr_lo = ta.LOWEST(14)
        self.vwap = ta.VWAP(); self.vol_ma_sma = ta.SMA(20)
        self.cci_sma = ta.SMA(i.cci_len); self.cci_dev_sma = ta.SMA(i.cci_len)
        self.kf_R_emp_sd = ta.STDEV(50)
        self.dv_rate_sd = ta.STDEV(100); self.dv_kf_sd = ta.STDEV(100); self.dv_pe_sd = ta.STDEV(100)
        self.dv_hi = ta.HIGHEST(i.div_lkb + 1); self.dv_lo = ta.LOWEST(i.div_lkb + 1)
        self.cc_hi = ta.HIGHEST(7); self.cc_lo = ta.LOWEST(7)
        self.ph_struct = ta.PIVOT(i.struct_piv, i.struct_piv, True); self.pl_struct = ta.PIVOT(i.struct_piv, i.struct_piv, False)
        self.po3_hi = ta.HIGHEST(i.po3_range_lkb); self.po3_lo = ta.LOWEST(i.po3_range_lkb)
        self.vd_vol_sma = ta.SMA(i.vd_lookback)
        self.vd_c_hi = ta.HIGHEST(i.vd_lookback); self.vd_c_lo = ta.LOWEST(i.vd_lookback)
        self.vd_d_hi = ta.HIGHEST(i.vd_lookback); self.vd_d_lo = ta.LOWEST(i.vd_lookback)
        self.vol_pct_rank = ta.PERCENTRANK(i.vol_rank_bars)
        self.ny_day_change = ta.CHANGE()

        # ── §4 RATE var state ──
        self.rate_uptrend = True; self.rate_st_line = NAN; self.rate_p_upper = NAN; self.rate_p_lower = NAN
        # §4.5 arming
        self.rate_flip_bar = -999; self.rate_flip_dir = 0; self.rate_flip_close = NAN; self.rate_flip_used = False
        # §6 zones: parallel lists [top, bot, score, touch, inzn, cbar]
        self.d_top: List[float] = []; self.d_bot: List[float] = []; self.d_score: List[float] = []
        self.d_touch: List[int] = []; self.d_inzn: List[bool] = []; self.d_cbar: List[int] = []
        self.s_top: List[float] = []; self.s_bot: List[float] = []; self.s_score: List[float] = []
        self.s_touch: List[int] = []; self.s_inzn: List[bool] = []; self.s_cbar: List[int] = []
        # §9 market profile
        self.MP_BINS = 200; self.mp_bin_sz = 1.0; self.mp_bins = [0.0] * 200
        self.session_low = NAN; self.session_high = NAN; self.mp_poc = NAN; self.mp_vah = NAN; self.mp_val = NAN
        self._p_in_session = False
        # §9.4 session structure
        self.on_hi_live = NAN; self.on_lo_live = NAN; self.on_hi_done = NAN; self.on_lo_done = NAN
        self.rth_open_px = NAN; self.f30_ret = NAN
        self.ib_hi = NAN; self.ib_lo = NAN; self.ib_hi_bar = NAN; self.ib_lo_bar = NAN; self.ib_close = NAN
        self.ib_last_ext = 0; self.ib_done = False
        self.hr_hi_live = NAN; self.hr_lo_live = NAN; self.prev_hr_hi = NAN; self.prev_hr_lo = NAN
        self.hr_open_inside = False; self.hb_up_hit = False; self.hb_dn_hit = False
        self.hb_up_bar = -999; self.hb_dn_bar = -999; self.hb_up_min = 0; self.hb_dn_min = 0
        self._p_in_on = False; self._p_in_rth = False; self._p_in_f30 = False; self._p_in_ib = False; self._p_hr = NAN
        self._fomc = [s for s in i.fomc_dates.replace(" ", "").split(",") if s]
        self._hv = [s for s in i.hv_open_dates.replace(" ", "").split(",") if s]
        # §9.5 Kalman / MAMA / shock
        self.kf_innov_abs = 0.0; self.kf_level = NAN; self.kf_vel = NAN
        self.kf_P00 = 1.0; self.kf_P01 = 0.0; self.kf_P11 = 1.0
        self.mama_val = NAN; self.fama_val = NAN; self.shock_bars_left = 0
        # §9.6 PE
        self.pe_counts = [0] * 24; self.pe_buf: List[int] = []; self.pe_wbuf: List[float] = []; self.pe_wsum = [0.0] * 24
        # §9.8 cyber cycle
        self.cc_val = 0.0
        # §9.9 structure
        self.struct_sh = NAN; self.struct_sh_prev = NAN; self.struct_sl = NAN; self.struct_sl_prev = NAN
        self.struct_sh_broken = True; self.struct_sl_broken = True; self.struct_bias = 0
        self.struct_sh_bar = NAN; self.struct_sl_bar = NAN
        self.struct_seq_bull = False; self.struct_seq_bear = False
        # §9.10 sweeps
        self.sweep_bars_since_hi = 999; self.sweep_bars_since_lo = 999
        # §9.11 order blocks
        self.ob_bull_top: List[float] = []; self.ob_bull_bot: List[float] = []; self.ob_bull_mit: List[bool] = []
        self.ob_bear_top: List[float] = []; self.ob_bear_bot: List[float] = []; self.ob_bear_mit: List[bool] = []
        self.ob_bars_since_bull = 999; self.ob_bars_since_bear = 999
        # §9.13 FVG / rejection / CISD
        self.fvg_bull_t: List[float] = []; self.fvg_bull_b: List[float] = []; self.fvg_bull_bar: List[int] = []
        self.fvg_bear_t: List[float] = []; self.fvg_bear_b: List[float] = []; self.fvg_bear_bar: List[int] = []
        self._rej = {k: 999 for k in ("bull_prevc", "bull_swing", "bull_fvg", "bull_ob", "bear_prevc", "bear_swing", "bear_fvg", "bear_ob")}
        self._rej_cluster_bull_bar = -999; self._rej_cluster_bear_bar = -999
        self._cisd_last_up_open = NAN; self._cisd_last_down_open = NAN
        self._p_cisd_bull = False; self._p_cisd_bear = False; self._p_choch_bull = False; self._p_choch_bear = False
        # §9.14 Po3
        self.po3_state = "ACCUMULATION"; self.po3_state_bar = 0
        # §9.15 TIDE
        self._tide_win_hi = NAN; self._tide_win_lo = NAN; self.tide_hi = NAN; self.tide_lo = NAN
        self.tide_broke_above = False; self.tide_broke_below = False; self.tide_inrange_closes = 0
        self._p_tide_in_win = False
        # empirical / time-of-day
        self.emp_mfe_pct_buf: List[float] = []; self.emp_buf_trend: List[float] = []; self.emp_buf_chop: List[float] = []
        self.tod_wins = [0] * 24; self.tod_losses = [0] * 24
        # §10 adaptive weights
        self.w_trade_count = 0; self.w_write_ptr = 0; self.w_outcome = [0] * 50
        self.snap = [[0] * 50 for _ in range(12)]          # snap[idx][slot]
        self.v_hits = [0] * 12; self.v_misses = [0] * 12; self.v_hits_nf = [0] * 12; self.v_misses_nf = [0] * 12
        # §11 filters
        self.bars_since_stop = 999; self.daily_pnl = 0.0; self._p_past_eod = False
        # §12 per-trade frozen state
        self.rate_tp1_dist = NAN; self.rate_tp2_dist = NAN; self.rate_sl_dist = NAN; self.rate_qty_plan = 0
        self.rate_tp1_done = False; self.rate_pend_dir = 0; self.rate_pend_bar = -999
        self.rate_sig_price = NAN; self.rate_best_price = NAN; self.trail_stop_long = NAN; self.trail_stop_short = NAN
        self.rate_be_armed = False; self.rate_tp1_bar = NAN
        self.tide_tp1_done = False; self.tide_tp2_lvl = NAN; self.tide_sl_lvl = NAN
        self._emp_was_open = False; self._emp_was_long = False; self._emp_ref_price = NAN; self._emp_entry_bar = NAN
        self.w_slot_queue: List[int] = []; self.tod_hour_queue: List[int] = []
        self.w_last_rec_entry_bar = -1; self._prev_closed = 0
        self._p_netprofit = NAN
        self._p_vd = (NAN, NAN, NAN, NAN)
        self.bar_index = -1
        self.state: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []               # signal-level events for the log
        self.paused = False                                  # runtime pause: no NEW entries (exits keep running)

    # ══════════════════════════════════════════════════════════════════
    def on_bar(self, bar: Bar, bar_index: int,
               htf: Sequence[Tuple[float, float]],
               ltf: Sequence[Tuple[float, float, float]],
               time_close: Optional[int] = None) -> Dict[str, Any]:
        """Evaluate the script on a CLOSED chart bar. `htf` = 5 × (dir, regime) for the
        HTF connections, `ltf` = 2 × (dir, bars_since_flip, regime) for 2m/5m.
        `time_close` = Pine's `time_close` (the session close for a truncated last bar)."""
        i = self.i
        em = self.em
        self.bar_index = bar_index
        mintick = self.mintick
        ts = bar.ts
        time_close = int(time_close) if time_close else ts + self.tf_minutes * 60
        _o, _h, _l, _c, volume = bar.o, bar.h, bar.l, bar.c, bar.v
        self.o.push(_o); self.h.push(_h); self.l.push(_l); self.c.push(_c); self.vol.push(volume)
        c, o, h, l, vol = self.c, self.o, self.h, self.l, self.vol

        # ── §1.5 derived position state (from the emulator's open trades, by entry id) ──
        rate_qty_open = 0; rate_pos_long = False; rate_avg_price = NAN; rate_entry_bar = NAN
        h4_qty_open = 0; h4_pos_long = False; h4_avg_price = NAN
        for t in em.open:
            if t.entry_id in ("Long", "Short"):
                rate_qty_open += t.qty; rate_pos_long = t.direction > 0
                rate_avg_price = t.entry_price; rate_entry_bar = t.entry_bar
            elif t.entry_id in ("TideLong", "TideShort"):
                h4_qty_open += t.qty; h4_pos_long = t.direction > 0; h4_avg_price = t.entry_price

        # ── §3 HTF bias / LTF failure ──
        htf_dirs = [x[0] for x in htf]; htf_regs = [x[1] for x in htf]
        htf_bull_count5 = sum(1 for d in htf_dirs if d == -1)
        htf_bear_count5 = sum(1 for d in htf_dirs if d == 1)
        htf_regime_avg = sum(nz(r, 0.5) for r in htf_regs) / 5.0
        mtf_long = htf_bull_count5 >= i.htf_min_bull_for_bias
        mtf_short = htf_bear_count5 >= i.htf_min_bull_for_bias
        htf_bull = int(pround(htf_bull_count5 / 5.0 * 2.0)); htf_bear = int(pround(htf_bear_count5 / 5.0 * 2.0))
        (ltf_2m_dir, ltf_2m_bsf, ltf_2m_regime), (ltf_5m_dir, ltf_5m_bsf, ltf_5m_regime) = ltf
        ltf_fail_long = i.use_ltf_check and ((ltf_2m_dir == 1 and ltf_2m_bsf <= i.ltf_instability_bars) or (ltf_5m_dir == 1 and ltf_5m_bsf <= i.ltf_instability_bars))
        ltf_fail_short = i.use_ltf_check and ((ltf_2m_dir == -1 and ltf_2m_bsf <= i.ltf_instability_bars) or (ltf_5m_dir == -1 and ltf_5m_bsf <= i.ltf_instability_bars))

        # ── §4 RATE engine ──
        rate_di_plus, rate_di_minus, rate_adx = self.dmi.update(_h, _l, _c)
        self.adx_s.push(rate_adx)
        rate_adx_score = pmin(pmax((rate_adx - 15.0) / 20.0, 0.0), 1.0)
        rate_atr_s = self.atr_fast.update(_h, _l, _c); rate_atr_l = self.atr_slow.update(_h, _l, _c)
        rate_vol_ratio = (rate_atr_s / rate_atr_l) if rate_atr_l > 0.0 else 1.0          # Pine: na > 0.0 is false -> 1.0
        rate_vol_score = pmin(pmax((rate_vol_ratio - 0.5) / 1.0, 0.0), 1.0)
        n = i.rate_eff_len
        rate_net = abs(_c - c[n]); rate_sum = 0.0
        for k in range(n):
            rate_sum += abs(c[k] - c[k + 1])
        rate_eff = (rate_net / rate_sum) if rate_sum > 0.0 else 0.0                      # Pine: na > 0.0 is false -> 0.0
        rate_eff_score = pmin(pmax((rate_eff - 0.1) / 0.35, 0.0), 1.0)
        rate_dir = 1 if _c > c[1] else -1
        rate_cons = 0.0
        for k in range(n):
            rate_cons += 1.0 if ((c[k] > c[k + 1]) == (rate_dir > 0)) else 0.0        # na comparisons are false, exactly as in Pine
        rate_cons_score = rate_cons / float(n)
        # FDI
        fdi_path = 0.0
        for k in range(i.fdi_len):
            fdi_path += abs(c[k] - c[k + 1])
        fdi_net = pmax(abs(_c - c[i.fdi_len]), 0.0001)
        fdi_raw = (1.0 + math.log(fdi_path / fdi_net) / math.log(2.0 * i.fdi_len)) if fdi_path > 0.0 else 1.5   # na > 0.0 false -> 1.5
        fdi = self.fdi_ema.update(fdi_raw)
        fdi = pmax(1.0, pmin(2.0, fdi))
        fdi_t = pmax(0.0, pmin(1.0, (fdi - 1.0) / 0.5))
        w_adx = 0.30 + (1.0 - fdi_t) * 0.10; w_vol = 0.30 + fdi_t * 0.10; w_eff = 0.25 + (1.0 - fdi_t) * 0.05; w_cons = 0.15 - fdi_t * 0.05
        rate_regime = self.regime_ema.update(rate_adx_score * w_adx + rate_vol_score * w_vol + rate_eff_score * w_eff + rate_cons_score * w_cons)
        self.regime_s.push(rate_regime)
        fdi_mult_adj = 1.0 + (fdi - 1.0) * 0.30
        rate_atr_mult = (i.rate_max_mult - (i.rate_max_mult - i.rate_min_mult) * rate_regime) * fdi_mult_adj
        rate_atr_mult = pmax(i.rate_min_mult, pmin(i.rate_max_mult, rate_atr_mult))
        # SuperTrend (hand-rolled, adaptive multiplier)
        rate_atr_val = self.atr_rate.update(_h, _l, _c)
        rate_hl2 = (_h + _l) / 2.0
        rate_upper_raw = rate_hl2 + rate_atr_mult * rate_atr_val
        rate_lower_raw = rate_hl2 - rate_atr_mult * rate_atr_val
        if na(self.rate_p_upper):
            self.rate_p_upper = rate_upper_raw; self.rate_p_lower = rate_lower_raw; self.rate_st_line = rate_lower_raw
        rate_lower = pmax(rate_lower_raw, self.rate_p_lower) if self.rate_uptrend else rate_lower_raw
        rate_upper = rate_upper_raw if self.rate_uptrend else pmin(rate_upper_raw, self.rate_p_upper)
        prev_uptrend = self.rate_uptrend
        if self.rate_uptrend:
            if _c < self.rate_p_lower:
                self.rate_uptrend = False; self.rate_st_line = rate_upper
            else:
                self.rate_st_line = rate_lower
        else:
            if _c > self.rate_p_upper:
                self.rate_uptrend = True; self.rate_st_line = rate_lower
            else:
                self.rate_st_line = rate_upper
        self.rate_p_upper = rate_upper if self.rate_uptrend else pmin(rate_upper_raw, self.rate_p_upper)
        self.rate_p_lower = pmax(rate_lower_raw, self.rate_p_lower) if self.rate_uptrend else rate_lower
        self.uptrend_s.push(self.rate_uptrend)
        up1 = self.uptrend_s[1]
        rate_long = self.rate_uptrend and (up1 is False)
        rate_short = (not self.rate_uptrend) and (up1 is True)
        rate_bull = self.rate_uptrend
        # Hurst (multi-window R/S)
        def f_rs_ratio(ln: int) -> float:
            s = 0.0
            for k in range(ln):
                s += (c[k] - c[k + 1])
            if na(s):
                return 1.0                                    # Pine: math.max(_cmax, na) -> na, (na > 0.0 and ...) false -> 1.0
            mean = s / ln; cum = 0.0; cmax = 0.0; cmin = 0.0; sq = 0.0
            for k in range(ln):
                dev = (c[k] - c[k + 1]) - mean
                cum += dev; cmax = max(cmax, cum); cmin = min(cmin, cum); sq += dev * dev
            R = cmax - cmin; S = math.sqrt(sq / ln)
            return R / S if (R > 0.0 and S > 0.0) else 1.0
        rs = [f_rs_ratio(10), f_rs_ratio(20), f_rs_ratio(30), f_rs_ratio(40)]
        lx = [math.log(10.0), math.log(20.0), math.log(30.0), math.log(40.0)]
        ly = [math.log(max(x, 0.0001)) for x in rs]
        lxm = sum(lx) / 4.0; lym = sum(ly) / 4.0
        hnum = sum((lx[k] - lxm) * (ly[k] - lym) for k in range(4)); hden = sum((lx[k] - lxm) ** 2 for k in range(4))
        hurst_raw = hnum / hden if hden > 0.0 else 0.5
        hurst_raw = max(0.0, min(1.0, hurst_raw))
        hurst = self.hurst_ema.update(hurst_raw)
        rate_regime_str = "TRANSITION"
        if rate_regime >= 0.65 and hurst > 0.55: rate_regime_str = "STRONG TREND"
        elif rate_regime >= 0.65 and hurst <= 0.55: rate_regime_str = "WEAK TREND"
        elif rate_regime >= 0.40 and hurst > 0.55: rate_regime_str = "EMERGING"
        elif rate_regime >= 0.40 and hurst < 0.40: rate_regime_str = "CHOPPY"
        elif hurst < 0.40: rate_regime_str = "MEAN-REV"
        regime_accel = (rate_regime - self.regime_s[3]) > 0.02

        # ── §5 Homodyne discriminator ──
        sp_v = (4.0 * _c + 3.0 * c[1] + 2.0 * c[2] + c[3]) / 10.0
        self.sp.push(sp_v); sp = self.sp
        detrender = 0.0962 * sp_v + 0.5769 * sp[2] - 0.5769 * sp[4] - 0.0962 * sp[6]
        self.detr.push(detrender); dt = self.detr
        I1_raw = dt[3]
        Q1_raw = 0.0962 * detrender + 0.5769 * dt[2] - 0.5769 * dt[4] - 0.0962 * dt[6]
        I1 = self.i1_ema.update(I1_raw); Q1 = self.q1_ema.update(Q1_raw)
        phase_raw = math.atan(abs(Q1 / I1)) if (not na(I1) and I1 != 0.0) else 0.0     # Pine: na != 0.0 is false -> 0.0
        if I1 >= 0.0 and Q1 >= 0.0: phase_angle = phase_raw                            # all-false on na -> the else branch (360 deg), as in Pine
        elif I1 < 0.0 and Q1 >= 0.0: phase_angle = math.pi - phase_raw
        elif I1 < 0.0 and Q1 < 0.0: phase_angle = math.pi + phase_raw
        else: phase_angle = 2.0 * math.pi - phase_raw
        phase_deg = phase_angle * 180.0 / math.pi
        self.phase_s.push(phase_deg)
        cycle_rising = (phase_deg > 270.0) or (phase_deg <= 90.0)
        cycle_falling = (phase_deg > 90.0) and (phase_deg <= 270.0)

        # ── §6 shared ATR14 / avg volume ──
        atr14 = pmax(self.atr14.update(_h, _l, _c), mintick)
        avg_vol = self.avg_vol_sma.update(volume)

        # ── §4.5 arming window ──
        if rate_long or rate_short:
            self.rate_flip_bar = bar_index; self.rate_flip_dir = 1 if rate_long else -1
            self.rate_flip_close = _c; self.rate_flip_used = False
        rate_bars_since_flip = bar_index - self.rate_flip_bar
        _arm_win_ok = rate_bars_since_flip <= (i.arm_bars if i.use_arm_window else 0)
        _arm_chase_l = i.arm_max_chase_atr <= 0.0 or na(self.rate_flip_close) or (_c - self.rate_flip_close) <= atr14 * i.arm_max_chase_atr
        _arm_chase_s = i.arm_max_chase_atr <= 0.0 or na(self.rate_flip_close) or (self.rate_flip_close - _c) <= atr14 * i.arm_max_chase_atr
        rate_armed_long = rate_bull and self.rate_flip_dir == 1 and _arm_win_ok and not self.rate_flip_used and _arm_chase_l
        rate_armed_short = (not rate_bull) and self.rate_flip_dir == -1 and _arm_win_ok and not self.rate_flip_used and _arm_chase_s

        # ── §6 supply / demand zones ──
        _d_hi_lkb = self.d_hi_lkb.update(_h); _s_lo_lkb = self.s_lo_lkb.update(_l)
        ph = self.ph_piv.update(_h); pl = self.pl_piv.update(_l)

        def f_zone_score(react: float, vol_r: float, htf_a: int) -> float:
            return min(react / 6.0, 1.0) * 30.0 + min(vol_r / 2.5, 1.0) * 20.0 + float(htf_a) / 2.0 * 25.0 + 10.0

        zp = i.zone_piv
        if not na(pl):
            z_top = h[zp]; z_bot = pl
            react = (_d_hi_lkb - pl) / atr14 if atr14 > 0.0 else 0.0
            vol_r = (vol[zp] / avg_vol) if (not na(avg_vol) and avg_vol > 0.0) else 1.0
            no_ovlp = all((z_bot > self.d_top[j] or z_top < self.d_bot[j]) for j in range(len(self.d_top)))
            if (not na(react)) and react >= i.zone_min_reac and no_ovlp:
                if len(self.d_top) >= i.max_zones_n:
                    for arr in (self.d_top, self.d_bot, self.d_score, self.d_touch, self.d_inzn, self.d_cbar):
                        arr.pop(0)
                zs = f_zone_score(react, nz(vol_r, 1.0), htf_bull)
                self.d_top.append(z_top); self.d_bot.append(z_bot); self.d_score.append(zs)
                self.d_touch.append(0); self.d_inzn.append(False); self.d_cbar.append(bar_index - zp)
        if not na(ph):
            z_top = ph; z_bot = l[zp]
            react = (ph - _s_lo_lkb) / atr14 if atr14 > 0.0 else 0.0
            vol_r = (vol[zp] / avg_vol) if (not na(avg_vol) and avg_vol > 0.0) else 1.0
            no_ovlp = all((z_bot > self.s_top[j] or z_top < self.s_bot[j]) for j in range(len(self.s_top)))
            if (not na(react)) and react >= i.zone_min_reac and no_ovlp:
                if len(self.s_top) >= i.max_zones_n:
                    for arr in (self.s_top, self.s_bot, self.s_score, self.s_touch, self.s_inzn, self.s_cbar):
                        arr.pop(0)
                zs = f_zone_score(react, nz(vol_r, 1.0), htf_bear)
                self.s_top.append(z_top); self.s_bot.append(z_bot); self.s_score.append(zs)
                self.s_touch.append(0); self.s_inzn.append(False); self.s_cbar.append(bar_index - zp)
        nearest_demand_dist = NAN; nearest_supply_dist = NAN; best_demand_tier = "W"; best_supply_tier = "W"
        for idx in range(len(self.d_top) - 1, -1, -1):
            zt = self.d_top[idx]; zb = self.d_bot[idx]; age = bar_index - self.d_cbar[idx]
            ap = 15.0 if age > 200 else 10.0 if age > 100 else 5.0 if age > 50 else 0.0
            eff = max(0.0, self.d_score[idx] - ap)
            was_in = self.d_inzn[idx]; is_in = _l <= zt and _h >= zb
            if is_in and not was_in:
                t = self.d_touch[idx] + 1; self.d_touch[idx] = t
                self.d_score[idx] = max(0.0, self.d_score[idx] + (10.0 if t == 1 else -8.0))
            self.d_inzn[idx] = is_in
            if _l > zt:
                dist = (_l - zt) / atr14
                if na(nearest_demand_dist) or dist < nearest_demand_dist:
                    nearest_demand_dist = dist; best_demand_tier = "E" if eff >= 75 else "S" if eff >= 50 else "W"
            if _c < zb - atr14 * 0.5:
                for arr in (self.d_top, self.d_bot, self.d_score, self.d_touch, self.d_inzn, self.d_cbar):
                    arr.pop(idx)
        for idx in range(len(self.s_top) - 1, -1, -1):
            zt = self.s_top[idx]; zb = self.s_bot[idx]; age = bar_index - self.s_cbar[idx]
            ap = 15.0 if age > 200 else 10.0 if age > 100 else 5.0 if age > 50 else 0.0
            eff = max(0.0, self.s_score[idx] - ap)
            was_in = self.s_inzn[idx]; is_in = _l <= zt and _h >= zb
            if is_in and not was_in:
                t = self.s_touch[idx] + 1; self.s_touch[idx] = t
                self.s_score[idx] = max(0.0, self.s_score[idx] + (10.0 if t == 1 else -8.0))
            self.s_inzn[idx] = is_in
            if _h < zb:
                dist = (zb - _h) / atr14
                if na(nearest_supply_dist) or dist < nearest_supply_dist:
                    nearest_supply_dist = dist; best_supply_tier = "E" if eff >= 75 else "S" if eff >= 50 else "W"
            if _c > zt + atr14 * 0.5:
                for arr in (self.s_top, self.s_bot, self.s_score, self.s_touch, self.s_inzn, self.s_cbar):
                    arr.pop(idx)

        # ── §7 shared indicators + CCI ──
        rsi_val = self.rsi.update(_c); self.rsi_s.push(rsi_val)
        rsi_slope = rsi_val - self.rsi_s[3]
        ftr_hi = self.ftr_hi.update(rsi_val); ftr_lo = self.ftr_lo.update(rsi_val); ftr_rng = ftr_hi - ftr_lo
        ftr_n = (2.0 * (rsi_val - ftr_lo) / ftr_rng - 1.0) if (not na(ftr_rng) and ftr_rng > 0.0) else (NAN if na(ftr_rng) else 0.0)
        ftr_c = pmax(-0.9999, pmin(0.9999, ftr_n))
        ftr_val = 0.5 * math.log((1.0 + ftr_c) / (1.0 - ftr_c)) if not na(ftr_c) else NAN
        self.ftr_s.push(ftr_val); ftr_sig = self.ftr_s[1]
        _hlc3 = (_h + _l + _c) / 3.0
        skey = self.session_key(ts); new_vwap_session = skey != self._last_session_key; self._last_session_key = skey
        vwap_val = self.vwap.update(_hlc3, volume, new_vwap_session)
        vol_ma = self.vol_ma_sma.update(volume)
        cci_tp = _hlc3; cci_sma = self.cci_sma.update(cci_tp)
        cci_dev = self.cci_dev_sma.update(abs(cci_tp - cci_sma))
        cci_val = ((cci_tp - cci_sma) / (0.015 * cci_dev)) if (not na(cci_dev) and cci_dev != 0.0) else (NAN if na(cci_dev) else 0.0)
        cci_long = cci_val > 0.0; cci_short = cci_val < 0.0

        # ── §8 XGBoost5 ──
        xf1 = pmin(pmax((rate_adx - 15.0) / 50.0, 0.0), 1.0)
        xf2 = pmin(pmax((hurst - 0.40) / 0.25, 0.0), 1.0)
        xf3 = pmin(pmax((1.50 - fdi) / 0.40, 0.0), 1.0)
        xf4_l = 0.20 if na(nearest_demand_dist) else min(1.0 / (nearest_demand_dist + 0.5), 1.0)
        xf4_s = 0.20 if na(nearest_supply_dist) else min(1.0 / (nearest_supply_dist + 0.5), 1.0)
        xf5_l = 1.0 if cycle_rising else 0.0; xf5_s = 1.0 if cycle_falling else 0.0
        XGB_ETA = 0.30
        t1_l = xf1 * 0.70 + 0.15 if rate_di_plus > rate_di_minus else 0.15
        t1_s = xf1 * 0.70 + 0.15 if rate_di_minus > rate_di_plus else 0.15
        r1_l = 1.0 - t1_l; r1_s = 1.0 - t1_s
        t2_l = r1_l * 0.65 if (xf2 > 0.50 and rate_bull) else r1_l * 0.15
        t2_s = r1_s * 0.65 if (xf2 > 0.50 and not rate_bull) else r1_s * 0.15
        p2_l = t1_l + XGB_ETA * t2_l; p2_s = t1_s + XGB_ETA * t2_s
        r2_l = 1.0 - p2_l; r2_s = 1.0 - p2_s
        t3_l = r2_l * 0.60 if (xf3 > 0.40 and xf4_l > 0.5) else r2_l * 0.10
        t3_s = r2_s * 0.60 if (xf3 > 0.40 and xf4_s > 0.5) else r2_s * 0.10
        p3_l = p2_l + XGB_ETA * t3_l; p3_s = p2_s + XGB_ETA * t3_s
        r3_l = 1.0 - p3_l; r3_s = 1.0 - p3_s
        t4_l = r3_l * 0.55 if rate_regime > 0.55 else r3_l * 0.20
        t4_s = r3_s * 0.55 if rate_regime > 0.55 else r3_s * 0.20
        p4_l = p3_l + XGB_ETA * t4_l; p4_s = p3_s + XGB_ETA * t4_s
        r4_l = 1.0 - p4_l; r4_s = 1.0 - p4_s
        t5_l = xf5_l * r4_l * 0.70; t5_s = xf5_s * r4_s * 0.70
        xgb_raw_l = p4_l + XGB_ETA * t5_l; xgb_raw_s = p4_s + XGB_ETA * t5_s
        xgb_prob_l = 1.0 / (1.0 + math.exp(-6.0 * (xgb_raw_l - 0.5))) if not na(xgb_raw_l) else NAN
        xgb_prob_s = 1.0 / (1.0 + math.exp(-6.0 * (xgb_raw_s - 0.5))) if not na(xgb_raw_s) else NAN
        xgb_long_ok = xgb_prob_l > 0.65; xgb_short_ok = xgb_prob_s > 0.65

        # ── §9 session + market profile ──
        in_sess = True
        if i.use_session:
            in_sess = in_session(ts, i.sess_window)
        new_session = in_sess and not self._p_in_session
        self._p_in_session = in_sess
        if new_session or na(self.session_low):
            self.session_low = _l; self.session_high = _h
            self.mp_bin_sz = max(1.0, pround(atr14 / float(i.mp_atr_div))) if not na(atr14) else 1.0
            self.mp_bins = [0.0] * self.MP_BINS
        if in_sess and not na(self.session_low):
            self.session_low = min(self.session_low, _l); self.session_high = max(self.session_high, _h)
            mp_idx = max(0, min(self.MP_BINS - 1, int(math.floor((_c - self.session_low) / self.mp_bin_sz))))
            self.mp_bins[mp_idx] += volume
            mp_total = 0.0; mp_maxvol = 0.0; mp_poc_i = 0
            for mi in range(self.MP_BINS):
                bv = self.mp_bins[mi]; mp_total += bv
                if bv > mp_maxvol:
                    mp_maxvol = bv; mp_poc_i = mi
            self.mp_poc = self.session_low + float(mp_poc_i) * self.mp_bin_sz
            if mp_total > 0.0:
                target = mp_total * 0.70; mp_run = mp_maxvol; lo_i = mp_poc_i; hi_i = mp_poc_i; safety = 0
                while mp_run < target and (lo_i > 0 or hi_i < self.MP_BINS - 1) and safety < self.MP_BINS:
                    nlo = self.mp_bins[lo_i - 1] if lo_i > 0 else -1.0
                    nhi = self.mp_bins[hi_i + 1] if hi_i < self.MP_BINS - 1 else -1.0
                    if nhi >= nlo:
                        hi_i += 1; mp_run += max(nhi, 0.0)
                    else:
                        lo_i -= 1; mp_run += max(nlo, 0.0)
                    safety += 1
                self.mp_val = self.session_low + float(lo_i) * self.mp_bin_sz
                self.mp_vah = self.session_low + float(hi_i) * self.mp_bin_sz
        mp_poc, mp_vah, mp_val = self.mp_poc, self.mp_vah, self.mp_val
        mp_mod_l = 0.0; mp_mod_s = 0.0
        if i.use_mp and i.use_session and in_sess and not na(mp_val) and not na(mp_vah):
            if _c <= mp_val + atr14 * 0.5: mp_mod_l = 0.5
            elif _c > mp_vah + atr14: mp_mod_l = -0.5
            if _c >= mp_vah - atr14 * 0.5: mp_mod_s = 0.5
            elif _c < mp_val - atr14: mp_mod_s = -0.5

        # ── §9.4 session structure priors / hour breach / midday / events ──
        _in_rth_v3 = in_session(ts, "0930-1600"); _in_on_v3 = in_session(ts, "1800-0930")
        _in_f30_v3 = in_session(ts, "0930-1000"); _in_ib_v3 = in_session(ts, "0930-1030")
        ny_h, ny_m = ny_hour_minute(ts); _mins_now_v3 = ny_h * 60 + ny_m
        if _in_on_v3 and not self._p_in_on:
            self.on_hi_live = _h; self.on_lo_live = _l
        elif _in_on_v3:
            self.on_hi_live = max(nz(self.on_hi_live, _h), _h); self.on_lo_live = min(nz(self.on_lo_live, _l), _l)
        if (not _in_on_v3) and self._p_in_on:
            self.on_hi_done = self.on_hi_live; self.on_lo_done = self.on_lo_live
        on_mid = (self.on_hi_done + self.on_lo_done) / 2.0 if (not na(self.on_hi_done) and not na(self.on_lo_done)) else NAN
        _rth_start_v3 = _in_rth_v3 and not self._p_in_rth
        if _rth_start_v3:
            self.rth_open_px = _o; self.f30_ret = NAN
        if (not _in_f30_v3) and self._p_in_f30 and not na(self.rth_open_px):
            self.f30_ret = c[1] - self.rth_open_px
        if _in_ib_v3 and not self._p_in_ib:
            self.ib_hi = _h; self.ib_lo = _l; self.ib_hi_bar = bar_index; self.ib_lo_bar = bar_index
            self.ib_close = NAN; self.ib_last_ext = 0; self.ib_done = False
        elif _in_ib_v3:
            if _h > nz(self.ib_hi, _h - 1.0): self.ib_hi = _h; self.ib_hi_bar = bar_index
            if _l < nz(self.ib_lo, _l + 1.0): self.ib_lo = _l; self.ib_lo_bar = bar_index
        if (not _in_ib_v3) and self._p_in_ib and not na(self.ib_hi):
            self.ib_close = c[1]; self.ib_last_ext = 1 if self.ib_hi_bar > self.ib_lo_bar else -1; self.ib_done = True
        ib_mid = (self.ib_hi + self.ib_lo) / 2.0 if (not na(self.ib_hi) and not na(self.ib_lo)) else NAN
        self._p_in_on, self._p_in_rth, self._p_in_f30, self._p_in_ib = _in_on_v3, _in_rth_v3, _in_f30_v3, _in_ib_v3
        sess_bias_dir = 0; sess_bias_str = 0.0; sess_bias_src = "--"
        if _in_rth_v3:
            if _mins_now_v3 >= 15 * 60 and not na(self.f30_ret) and self.f30_ret != 0.0:
                sess_bias_dir = 1 if self.f30_ret > 0.0 else -1; sess_bias_str = 0.8; sess_bias_src = "F30"
            elif self.ib_done and not na(self.ib_close) and not na(ib_mid) and self.ib_close != ib_mid:
                sess_bias_dir = 1 if self.ib_close > ib_mid else -1
                sess_bias_str = 1.0 if self.ib_last_ext == sess_bias_dir else 0.7; sess_bias_src = "IB"
            elif (not self.ib_done) and not na(self.rth_open_px) and not na(on_mid) and self.rth_open_px != on_mid:
                sess_bias_dir = 1 if self.rth_open_px > on_mid else -1; sess_bias_str = 0.8; sess_bias_src = "ON"
        _hr_now_v3 = ny_h
        _new_hour = nz(self._p_hr, -1) != _hr_now_v3
        self._p_hr = _hr_now_v3
        if _new_hour:
            self.prev_hr_hi = self.hr_hi_live; self.prev_hr_lo = self.hr_lo_live
            self.hr_hi_live = _h; self.hr_lo_live = _l
            self.hr_open_inside = (not na(self.prev_hr_hi)) and (not na(self.prev_hr_lo)) and _o < self.prev_hr_hi and _o > self.prev_hr_lo
            self.hb_up_hit = False; self.hb_dn_hit = False
        else:
            self.hr_hi_live = max(nz(self.hr_hi_live, _h), _h); self.hr_lo_live = min(nz(self.hr_lo_live, _l), _l)
        if (not self.hb_up_hit) and not na(self.prev_hr_hi) and _h > self.prev_hr_hi:
            self.hb_up_hit = True; self.hb_up_bar = bar_index; self.hb_up_min = ny_m
        if (not self.hb_dn_hit) and not na(self.prev_hr_lo) and _l < self.prev_hr_lo:
            self.hb_dn_hit = True; self.hb_dn_bar = bar_index; self.hb_dn_min = ny_m
        hb_timing_l = ((-1 if self.hb_up_min < 20 else 1 if self.hb_up_min >= 40 else 0) if (bar_index - self.hb_up_bar) <= 1 else 0)
        hb_timing_s = ((-1 if self.hb_dn_min < 20 else 1 if self.hb_dn_min >= 40 else 0) if (bar_index - self.hb_dn_bar) <= 1 else 0)
        in_midday = in_session(ts, i.midday_window)
        _today_str = ny_date_str(ts)
        is_fomc_day = i.use_event_blackout and _today_str in self._fomc
        is_hv_day = i.use_hv_open_block and _today_str in self._hv
        fomc_block = is_fomc_day and in_session(ts, i.fomc_window)
        hv_block = is_hv_day and in_session(ts, i.hv_open_window)
        midday_block = i.midday_mode == "Block" and in_midday

        # ── §9.5 Kalman-CFV + MAMA/FAMA + shock ──
        cfv_mp_component = mp_poc if (i.use_mp and i.use_session and in_sess and not na(mp_poc)) else vwap_val
        cfv_base = (vwap_val + cfv_mp_component) / 2.0
        cfv_pull = 0.0
        if not na(nearest_demand_dist) and best_demand_tier == "E" and nearest_demand_dist < 1.5:
            cfv_pull = -atr14 * (1.5 - nearest_demand_dist) * 0.15
        if not na(nearest_supply_dist) and best_supply_tier == "E" and nearest_supply_dist < 1.5:
            cfv_pull = cfv_pull + atr14 * (1.5 - nearest_supply_dist) * 0.15
        cfv = cfv_base + cfv_pull
        kf_innov_z = 0.0
        _kf_R_emp = pmax(self.kf_R_emp_sd.update(self.kf_innov_abs), mintick) ** 2
        if i.use_kalman:
            _kf_ready = (not i.kf_cold_start_fix) or (not na(cfv) and not na(atr14) and not na(fdi_t) and not na(rate_regime) and not na(_kf_R_emp))
            if na(self.kf_level) or not _kf_ready:
                self.kf_level = cfv; self.kf_vel = 0.0
                if i.kf_cold_start_fix:
                    self.kf_P00 = 1.0; self.kf_P01 = 0.0; self.kf_P11 = 1.0
            else:
                _kf_R_heur = (atr14 * (i.kf_r_base + fdi_t * i.kf_r_fdi_gain)) ** 2
                kf_R = (_kf_R_heur * (1.0 - i.kf_adapt_blend) + _kf_R_emp * i.kf_adapt_blend) if i.use_adaptive_kf_r else _kf_R_heur
                kf_qsc = i.kf_q_base + (1.0 - fdi_t) * 0.10 + rate_regime * 0.10
                kf_QL = (atr14 * kf_qsc * 0.25) ** 2; kf_QV = (atr14 * kf_qsc) ** 2
                kf_level_pred = self.kf_level + self.kf_vel; kf_vel_pred = self.kf_vel
                kf_P00_pred = pmax(self.kf_P00 + 2.0 * self.kf_P01 + self.kf_P11 + kf_QL, 0.0001)
                kf_P01_pred = self.kf_P01 + self.kf_P11
                kf_P11_pred = pmax(self.kf_P11 + kf_QV, 0.0001)
                kf_y = cfv - kf_level_pred; kf_S = kf_P00_pred + kf_R
                kf_KL = kf_P00_pred / kf_S; kf_KV = kf_P01_pred / kf_S
                self.kf_level = kf_level_pred + kf_KL * kf_y
                self.kf_vel = kf_vel_pred + kf_KV * kf_y
                self.kf_P00 = pmax((1.0 - kf_KL) * kf_P00_pred, 0.0001)
                self.kf_P01 = (1.0 - kf_KL) * kf_P01_pred
                self.kf_P11 = pmax(kf_P11_pred - kf_KV * kf_P01_pred, 0.0001)
                kf_innov_z = kf_y / math.sqrt(kf_S) if (not na(kf_S) and kf_S > 0) else NAN
                self.kf_innov_abs = abs(kf_y)
        kf_level, kf_vel = self.kf_level, self.kf_vel
        self.kfvel_s.push(kf_vel)
        kf_long_ok = i.use_kalman and not na(kf_vel) and kf_vel > 0.0
        kf_short_ok = i.use_kalman and not na(kf_vel) and kf_vel < 0.0
        mama_dp = abs(phase_deg - self.phase_s[1])
        if mama_dp > 180.0:
            mama_dp = 360.0 - mama_dp
        mama_dp = pmax(1.0, pmin(180.0, mama_dp))
        mama_alpha = i.mama_fast_lim * 18.0 / mama_dp
        mama_alpha = pmax(i.mama_slow_lim, pmin(i.mama_fast_lim, mama_alpha))
        if i.use_pma:
            if na(self.mama_val):
                self.mama_val = _c; self.fama_val = _c
            else:
                self.mama_val = mama_alpha * _c + (1.0 - mama_alpha) * self.mama_val
                self.fama_val = 0.5 * mama_alpha * self.mama_val + (1.0 - 0.5 * mama_alpha) * self.fama_val
        mama_val, fama_val = self.mama_val, self.fama_val
        pma_long_ok = i.use_pma and not na(mama_val) and mama_val > fama_val
        pma_short_ok = i.use_pma and not na(mama_val) and mama_val < fama_val
        mama_spread = (mama_val - fama_val) if (not na(mama_val) and not na(fama_val)) else 0.0
        dom_period_f = pmax(8.0, pmin(48.0, i.mama_fast_lim * 20.0 / pmax(mama_alpha, i.mama_slow_lim)))
        dom_period_i = int(pround(dom_period_f)) if not na(dom_period_f) else NAN        # na -> every dv_bucket comparison false -> 48
        if i.use_kalman and not na(kf_innov_z) and abs(kf_innov_z) >= i.shock_z_thresh:
            self.shock_bars_left = i.shock_decay_bars
        elif self.shock_bars_left > 0:
            self.shock_bars_left -= 1
        shock_decay_frac = float(self.shock_bars_left) / float(i.shock_decay_bars) if i.shock_decay_bars > 0 else 0.0
        shock_mult = 1.0 + (i.shock_boost_mult - 1.0) * shock_decay_frac

        # ── §9.6 permutation entropy + TRC ──
        pe_norm = 0.5
        # The Pine runs this block on EVERY bar. With `use_pe_weighted`, `_pe_w = math.max(0.01, range/atr14)` is na
        # while atr14 (bars 0-12) or _c[3] is na (math.max with na -> na, A2); `array.set(pe_wsum, p, get + na)`
        # poisons that bin for the life of the script, pe_wtotal is na forever, and pe_norm == 0.0 from bar 24 on -
        # so vote #10 fires on every bar in the RATE direction and the PE divergence never fires. That is what
        # TradingView runs (default). `pe_na_poison_fix` = the v3.3 patch: skip the block until the inputs are numbers.
        _pe_inputs_ok = not na(c[3]) and not na(atr14)
        if i.use_pe and (_pe_inputs_ok or not i.pe_na_poison_fix):
            a, b, cc_, d = _c, c[1], c[2], c[3]
            _ra = (a > b) + (a > cc_) + (a > d); _rb = (b >= a) + (b > cc_) + (b > d); _rc = (cc_ >= a) + (cc_ >= b) + (cc_ > d)
            _idx = _ra * 6 + (_rb - 1 if _rb > _ra else _rb) * 2 + ((_rc - 2 if _rc > _rb else _rc - 1) if _rc > _ra else (_rc - 1 if _rc > _rb else _rc))
            pe_pat_now = max(0, min(23, _idx))
            if i.use_pe_weighted:
                _pe_w = pmax(0.01, (pmax(pmax(a, b), pmax(cc_, d)) - pmin(pmin(a, b), pmin(cc_, d))) / atr14)   # na-propagating (Pine math.max)
            else:
                _pe_w = 1.0
            self.pe_buf.append(pe_pat_now); self.pe_wbuf.append(_pe_w)
            self.pe_counts[pe_pat_now] += 1; self.pe_wsum[pe_pat_now] += _pe_w
            if len(self.pe_buf) > i.pe_len:
                pe_old = self.pe_buf.pop(0); pe_wold = self.pe_wbuf.pop(0)
                self.pe_counts[pe_old] = max(0, self.pe_counts[pe_old] - 1)
                self.pe_wsum[pe_old] = pmax(0.0, self.pe_wsum[pe_old] - pe_wold)
            pe_h = 0.0; pe_total = len(self.pe_buf); pe_wtotal = sum(self.pe_wsum)
            if pe_total > 0 and pe_wtotal > 0.0:
                for pi in range(24):
                    pj = (self.pe_wsum[pi] / pe_wtotal) if i.use_pe_weighted else (float(self.pe_counts[pi]) / float(pe_total))
                    if pj > 0.0:
                        pe_h -= pj * math.log(pj)
            pe_norm = pe_h / math.log(24.0) if pe_total >= 24 else 0.5
            pe_norm = max(0.0, min(1.0, pe_norm))
        self.pe_s.push(pe_norm)
        pe_long_ok = i.use_pe and pe_norm < i.pe_thresh and rate_bull
        pe_short_ok = i.use_pe and pe_norm < i.pe_thresh and not rate_bull
        trc_trending = i.use_pe and fdi < i.pe_trc_fdi and hurst > i.pe_trc_hst and pe_norm < i.pe_thresh

        # ── §9.7 composite divergence veto ──
        rg, kv, pes = self.regime_s, self.kfvel_s, self.pe_s
        dv_bucket = 8 if dom_period_i <= 12 else 18 if dom_period_i <= 23 else 30 if dom_period_i <= 38 else 48
        dv_use_adaptive = i.div_adaptive and i.use_pma and not na(mama_val)
        if dv_use_adaptive:
            dv_rate_ref = rg[dv_bucket]; dv_kfv_ref = nz(kv[dv_bucket], 0.0); dv_pe_ref = pes[dv_bucket]
        else:
            dv_rate_ref = rg[i.div_lkb]; dv_kfv_ref = nz(kv[i.div_lkb], 0.0); dv_pe_ref = pes[i.div_lkb]
        dv_hi_ref = self.dv_hi.update(_h); dv_lo_ref = self.dv_lo.update(_l)
        dv_at_hi = i.use_div_veto and _h >= dv_hi_ref
        _dv_rate_sd = pmax(self.dv_rate_sd.update(rate_regime), 0.001)
        _dv_kf_sd = pmax(self.dv_kf_sd.update(nz(kf_vel, 0.0)), 0.000001)
        _dv_pe_sd = pmax(self.dv_pe_sd.update(pe_norm), 0.001)
        dv_rate_div_l = dv_at_hi and rate_regime < dv_rate_ref - _dv_rate_sd * i.dv_sd_mult
        dv_kf_div_l = dv_at_hi and not na(kf_vel) and kf_vel < dv_kfv_ref - _dv_kf_sd * i.dv_sd_mult
        dv_pe_div_l = dv_at_hi and pe_norm > dv_pe_ref + _dv_pe_sd * i.dv_sd_mult
        dv_count_l = int(dv_rate_div_l) + int(dv_kf_div_l) + int(dv_pe_div_l)
        diverge_veto_l = i.use_div_veto and dv_count_l >= i.div_min_count
        dv_at_lo = i.use_div_veto and _l <= dv_lo_ref
        dv_rate_div_s = dv_at_lo and rate_regime < dv_rate_ref - _dv_rate_sd * i.dv_sd_mult
        dv_kf_div_s = dv_at_lo and not na(kf_vel) and kf_vel > dv_kfv_ref + _dv_kf_sd * i.dv_sd_mult
        dv_pe_div_s = dv_at_lo and pe_norm > dv_pe_ref + _dv_pe_sd * i.dv_sd_mult
        dv_count_s = int(dv_rate_div_s) + int(dv_kf_div_s) + int(dv_pe_div_s)
        diverge_veto_s = i.use_div_veto and dv_count_s >= i.div_min_count

        # ── §9.8 cyber cycle ──
        _cc_1ma = 1.0 - i.cc_alpha_inp; _cc_half_sq = (1.0 - 0.5 * i.cc_alpha_inp) ** 2; _cc_1ma_sq = _cc_1ma ** 2
        cc_prev1 = self.cc_s[0]; cc_prev2 = self.cc_s[1]      # cc_val[1], cc_val[2] before this bar's push
        cc_new = _cc_half_sq * (_c - 2.0 * nz(c[1], _c) + nz(c[2], _c)) + 2.0 * _cc_1ma * nz(cc_prev1, 0.0) - _cc_1ma_sq * nz(cc_prev2, 0.0)
        self.cc_val = cc_new; self.cc_s.push(cc_new)
        cc_val = cc_new
        cc_hi = self.cc_hi.update(cc_val); cc_lo = self.cc_lo.update(cc_val); cc_rng = cc_hi - cc_lo
        cc_stoch = (cc_val - cc_lo) / cc_rng if (not na(cc_rng) and cc_rng > 0.0) else 0.5
        cc_long_ok = i.use_cc and cc_val > nz(cc_prev1, cc_val) and cc_stoch < 0.5 and rate_bull
        cc_short_ok = i.use_cc and cc_val < nz(cc_prev1, cc_val) and cc_stoch > 0.5 and not rate_bull

        # ── §9.9 swing structure + BOS / CHoCH ──
        ph_struct = self.ph_struct.update(_h); pl_struct = self.pl_struct.update(_l)
        struct_new_sh = i.use_struct and not na(ph_struct); struct_new_sl = i.use_struct and not na(pl_struct)
        if struct_new_sh:
            self.struct_sh_prev = self.struct_sh; self.struct_sh = ph_struct; self.struct_sh_broken = False
            self.struct_sh_bar = bar_index - i.struct_piv
        if struct_new_sl:
            self.struct_sl_prev = self.struct_sl; self.struct_sl = pl_struct; self.struct_sl_broken = False
            self.struct_sl_bar = bar_index - i.struct_piv
        struct_sh, struct_sl = self.struct_sh, self.struct_sl
        struct_is_hh = struct_new_sh and not na(self.struct_sh_prev) and struct_sh > self.struct_sh_prev
        struct_is_lh = struct_new_sh and not na(self.struct_sh_prev) and struct_sh <= self.struct_sh_prev
        struct_is_hl = struct_new_sl and not na(self.struct_sl_prev) and struct_sl > self.struct_sl_prev
        struct_is_ll = struct_new_sl and not na(self.struct_sl_prev) and struct_sl <= self.struct_sl_prev
        if struct_is_hh or struct_is_hl:
            self.struct_seq_bull = True; self.struct_seq_bear = False
        if struct_is_ll or struct_is_lh:
            self.struct_seq_bear = True; self.struct_seq_bull = False
        struct_break_sh_now = i.use_struct and not self.struct_sh_broken and not na(struct_sh) and _c > struct_sh
        struct_break_sl_now = i.use_struct and not self.struct_sl_broken and not na(struct_sl) and _c < struct_sl
        bos_bull = choch_bull = bos_bear = choch_bear = False
        if struct_break_sh_now:
            self.struct_sh_broken = True
            if self.struct_bias == -1: choch_bull = True
            else: bos_bull = True
            self.struct_bias = 1
        if struct_break_sl_now:
            self.struct_sl_broken = True
            if self.struct_bias == 1: choch_bear = True
            else: bos_bear = True
            self.struct_bias = -1

        # ── §9.10 liquidity sweeps ──
        _sweep_sh_age_ok = (bar_index - self.struct_sh_bar) >= i.sweep_min_level_age if not na(self.struct_sh_bar) else False
        _sweep_sl_age_ok = (bar_index - self.struct_sl_bar) >= i.sweep_min_level_age if not na(self.struct_sl_bar) else False
        sweep_high = i.use_sweep and not self.struct_sh_broken and not na(struct_sh) and _h > struct_sh and _c < struct_sh and _sweep_sh_age_ok and (_h - struct_sh) >= atr14 * i.sweep_min_wick_atr
        sweep_low = i.use_sweep and not self.struct_sl_broken and not na(struct_sl) and _l < struct_sl and _c > struct_sl and _sweep_sl_age_ok and (struct_sl - _l) >= atr14 * i.sweep_min_wick_atr
        if sweep_high: self.sweep_bars_since_hi = 0
        elif self.sweep_bars_since_hi < 999: self.sweep_bars_since_hi += 1
        if sweep_low: self.sweep_bars_since_lo = 0
        elif self.sweep_bars_since_lo < 999: self.sweep_bars_since_lo += 1

        # ── §9.11 order blocks ──
        ob_bull_disp = i.use_ob and (_c - _o) > atr14 * i.ob_disp_mult
        ob_bear_disp = i.use_ob and (_o - _c) > atr14 * i.ob_disp_mult
        ob_bull_origin = ob_bull_disp and c[1] < o[1]
        ob_bear_origin = ob_bear_disp and c[1] > o[1]
        if ob_bull_origin:
            if len(self.ob_bull_top) >= i.ob_max_count:
                self.ob_bull_top.pop(0); self.ob_bull_bot.pop(0); self.ob_bull_mit.pop(0)
            self.ob_bull_top.append(h[1]); self.ob_bull_bot.append(l[1]); self.ob_bull_mit.append(False)
        if ob_bear_origin:
            if len(self.ob_bear_top) >= i.ob_max_count:
                self.ob_bear_top.pop(0); self.ob_bear_bot.pop(0); self.ob_bear_mit.pop(0)
            self.ob_bear_top.append(h[1]); self.ob_bear_bot.append(l[1]); self.ob_bear_mit.append(False)
        ob_bull_fresh_touch = False; ob_bear_fresh_touch = False
        for idx in range(len(self.ob_bull_top) - 1, -1, -1):
            _t = self.ob_bull_top[idx]; _b = self.ob_bull_bot[idx]
            _in_now = _l <= _t and _h >= _b
            if _in_now and not self.ob_bull_mit[idx]:
                self.ob_bull_mit[idx] = True; ob_bull_fresh_touch = True
            if _c < _b - atr14 * i.ob_invalidate_atr:
                self.ob_bull_top.pop(idx); self.ob_bull_bot.pop(idx); self.ob_bull_mit.pop(idx)
        for idx in range(len(self.ob_bear_top) - 1, -1, -1):
            _t = self.ob_bear_top[idx]; _b = self.ob_bear_bot[idx]
            _in_now = _l <= _t and _h >= _b
            if _in_now and not self.ob_bear_mit[idx]:
                self.ob_bear_mit[idx] = True; ob_bear_fresh_touch = True
            if _c > _t + atr14 * i.ob_invalidate_atr:
                self.ob_bear_top.pop(idx); self.ob_bear_bot.pop(idx); self.ob_bear_mit.pop(idx)
        if ob_bull_fresh_touch: self.ob_bars_since_bull = 0
        elif self.ob_bars_since_bull < 999: self.ob_bars_since_bull += 1
        if ob_bear_fresh_touch: self.ob_bars_since_bear = 0
        elif self.ob_bars_since_bear < 999: self.ob_bars_since_bear += 1
        ob_in_fresh_bull = self.ob_bars_since_bull <= i.smc_confirm_window
        ob_in_fresh_bear = self.ob_bars_since_bear <= i.smc_confirm_window

        # ── §9.12 premium / discount + OTE ──
        pd_ready = i.use_premdisc and not na(struct_sh) and not na(struct_sl) and struct_sh > struct_sl
        pd_range = struct_sh - struct_sl if pd_ready else NAN
        pd_pct = (_c - struct_sl) / pd_range if (pd_ready and pd_range > 0.0) else NAN
        pd_zone = "N/A"
        if pd_ready:
            pd_zone = "EQUILIB"
            if pd_pct >= 0.70: pd_zone = "PREMIUM"
            elif pd_pct <= 0.30: pd_zone = "DISCOUNT"
        pd_ote_long = pd_ready and 0.21 <= pd_pct <= 0.382
        pd_ote_short = pd_ready and 0.618 <= pd_pct <= 0.79

        # ── §9.13 FVG / rejection cluster / CISD ──
        _fvg_bull_raw = _l > h[2]; _fvg_bear_raw = _h < l[2]
        _fvg_bull_size = (_l - h[2]) if _fvg_bull_raw else 0.0
        _fvg_bear_size = (l[2] - _h) if _fvg_bear_raw else 0.0
        fvg_bull = _fvg_bull_raw and _fvg_bull_size >= atr14 * i.fvg_min_size_atr
        fvg_bear = _fvg_bear_raw and _fvg_bear_size >= atr14 * i.fvg_min_size_atr
        fvg_max = 6
        if fvg_bull:
            if len(self.fvg_bull_t) >= fvg_max:
                self.fvg_bull_t.pop(0); self.fvg_bull_b.pop(0); self.fvg_bull_bar.pop(0)
            self.fvg_bull_t.append(_l); self.fvg_bull_b.append(h[2]); self.fvg_bull_bar.append(bar_index)
        if fvg_bear:
            if len(self.fvg_bear_t) >= fvg_max:
                self.fvg_bear_t.pop(0); self.fvg_bear_b.pop(0); self.fvg_bear_bar.pop(0)
            self.fvg_bear_t.append(l[2]); self.fvg_bear_b.append(_h); self.fvg_bear_bar.append(bar_index)
        for idx in range(len(self.fvg_bull_t) - 1, -1, -1):
            if _c < self.fvg_bull_b[idx] or (bar_index - self.fvg_bull_bar[idx]) > i.fvg_max_age:
                self.fvg_bull_t.pop(idx); self.fvg_bull_b.pop(idx); self.fvg_bull_bar.pop(idx)
        for idx in range(len(self.fvg_bear_t) - 1, -1, -1):
            if _c > self.fvg_bear_t[idx] or (bar_index - self.fvg_bear_bar[idx]) > i.fvg_max_age:
                self.fvg_bear_t.pop(idx); self.fvg_bear_b.pop(idx); self.fvg_bear_bar.pop(idx)
        _rej_range = _h - _l
        _rej_lower_wick = (min(_o, _c) - _l) / _rej_range if _rej_range > 0.0 else 0.0
        _rej_upper_wick = (_h - max(_o, _c)) / _rej_range if _rej_range > 0.0 else 0.0
        rej_prevcandle_bull = _l < l[1] and _c > l[1] and _rej_lower_wick >= i.rej_min_wick_ratio
        rej_prevcandle_bear = _h > h[1] and _c < h[1] and _rej_upper_wick >= i.rej_min_wick_ratio
        rej_swing_bull = sweep_low; rej_swing_bear = sweep_high
        rej_fvg_bull = any(_l <= t_ and _l >= b_ and _c > t_ and _rej_lower_wick >= i.rej_min_wick_ratio for t_, b_ in zip(self.fvg_bull_t, self.fvg_bull_b))
        rej_fvg_bear = any(_h >= b_ and _h <= t_ and _c < b_ and _rej_upper_wick >= i.rej_min_wick_ratio for t_, b_ in zip(self.fvg_bear_t, self.fvg_bear_b))
        rej_ob_bull = any(_l <= t_ and _l >= b_ and _c > t_ and _rej_lower_wick >= i.rej_min_wick_ratio for t_, b_ in zip(self.ob_bull_top, self.ob_bull_bot))
        rej_ob_bear = any(_h >= b_ and _h <= t_ and _c < b_ and _rej_upper_wick >= i.rej_min_wick_ratio for t_, b_ in zip(self.ob_bear_top, self.ob_bear_bot))
        R = self._rej
        def _tick(key: str, fired: bool) -> None:
            R[key] = 0 if fired else (R[key] + 1 if R[key] < 999 else 999)
        _tick("bull_prevc", rej_prevcandle_bull); _tick("bull_swing", rej_swing_bull); _tick("bull_fvg", rej_fvg_bull); _tick("bull_ob", rej_ob_bull)
        _tick("bear_prevc", rej_prevcandle_bear); _tick("bear_swing", rej_swing_bear); _tick("bear_fvg", rej_fvg_bear); _tick("bear_ob", rej_ob_bear)
        w = i.rej_cluster_window
        rej_cluster_count_bull = sum(1 for k in ("bull_prevc", "bull_swing", "bull_fvg", "bull_ob") if R[k] <= w)
        rej_cluster_count_bear = sum(1 for k in ("bear_prevc", "bear_swing", "bear_fvg", "bear_ob") if R[k] <= w)
        rej_cluster_bull = i.use_rejection_cluster and rej_cluster_count_bull >= i.rej_min_cluster
        rej_cluster_bear = i.use_rejection_cluster and rej_cluster_count_bear >= i.rej_min_cluster
        if rej_cluster_bull: self._rej_cluster_bull_bar = bar_index
        if rej_cluster_bear: self._rej_cluster_bear_bar = bar_index
        _in_expansion_window_bull = (bar_index - self._rej_cluster_bull_bar) <= i.expansion_confirm_bars
        _in_expansion_window_bear = (bar_index - self._rej_cluster_bear_bar) <= i.expansion_confirm_bars
        expansion_confirmed_bull = _in_expansion_window_bull and (_c - _o) >= atr14 * i.expansion_min_atr
        expansion_confirmed_bear = _in_expansion_window_bear and (_o - _c) >= atr14 * i.expansion_min_atr
        if _c > _o: self._cisd_last_up_open = _o
        if _c < _o: self._cisd_last_down_open = _o
        cisd_bull = i.use_cisd and not na(self._cisd_last_down_open) and _c > self._cisd_last_down_open and c[1] <= self._cisd_last_down_open
        cisd_bear = i.use_cisd and not na(self._cisd_last_up_open) and _c < self._cisd_last_up_open and c[1] >= self._cisd_last_up_open

        # ── §9.14 Power of Three ──
        po3_tight_range = (self.po3_hi.update(_h) - self.po3_lo.update(_l)) < atr14 * i.po3_accum_range_mult
        po3_low_regime = rate_regime < i.po3_accum_regime_max
        po3_low_adx = rate_adx < i.po3_accum_adx_max
        po3_no_events = not (choch_bull or choch_bear or sweep_high or sweep_low or cisd_bull or cisd_bear)
        po3_accumulation_now = po3_tight_range and po3_low_regime and po3_low_adx and po3_no_events
        po3_manip_trigger = i.use_po3 and (sweep_high or sweep_low or cisd_bull or cisd_bear) and self.po3_state == "ACCUMULATION"
        po3_dist_trigger = i.use_po3 and self.po3_state == "MANIPULATION" and (rate_regime > self.regime_s[3]) and (rate_adx > self.adx_s[3]) and (rej_cluster_bull or rej_cluster_bear)
        if po3_manip_trigger:
            self.po3_state = "MANIPULATION"; self.po3_state_bar = bar_index
        elif po3_dist_trigger:
            self.po3_state = "DISTRIBUTION"; self.po3_state_bar = bar_index
        elif po3_accumulation_now and self.po3_state == "DISTRIBUTION":
            self.po3_state = "ACCUMULATION"; self.po3_state_bar = bar_index
        po3_state = self.po3_state
        _delivery_shift_recent_bull = cisd_bull or choch_bull or self._p_cisd_bull or self._p_choch_bull
        _delivery_shift_recent_bear = cisd_bear or choch_bear or self._p_cisd_bear or self._p_choch_bear
        self._p_cisd_bull, self._p_cisd_bear, self._p_choch_bull, self._p_choch_bear = cisd_bull, cisd_bear, choch_bull, choch_bear
        rej_cluster_bull_confirmed = rej_cluster_bull and _delivery_shift_recent_bull and (not i.use_po3_gate_rejection or po3_state == "MANIPULATION")
        rej_cluster_bear_confirmed = rej_cluster_bear and _delivery_shift_recent_bear and (not i.use_po3_gate_rejection or po3_state == "MANIPULATION")

        # ── §9.15 TIDE ──
        _tide_in_win = in_session(ts, "0500-0900") or in_session(ts, "0900-1300") or in_session(ts, "1300-1700")
        _tide_win_start = _tide_in_win and not self._p_tide_in_win
        _tide_win_end = (not _tide_in_win) and self._p_tide_in_win
        self._p_tide_in_win = _tide_in_win
        if _tide_win_start:
            self._tide_win_hi = _h; self._tide_win_lo = _l
        elif _tide_in_win:
            self._tide_win_hi = pmax(self._tide_win_hi, _h); self._tide_win_lo = pmin(self._tide_win_lo, _l)
        if _tide_win_end:
            self.tide_hi = self._tide_win_hi; self.tide_lo = self._tide_win_lo
        tide_hi, tide_lo = self.tide_hi, self.tide_lo
        tide_above = i.use_tide and not na(tide_hi) and _c > tide_hi
        tide_below = i.use_tide and not na(tide_lo) and _c < tide_lo
        if tide_above:
            self.tide_broke_above = True; self.tide_broke_below = False; self.tide_inrange_closes = 0
        elif tide_below:
            self.tide_broke_below = True; self.tide_broke_above = False; self.tide_inrange_closes = 0
        elif self.tide_broke_above or self.tide_broke_below:
            self.tide_inrange_closes += 1
        tide_return_raw_bull = self.tide_broke_below and self.tide_inrange_closes == i.tide_confirm_bars
        tide_return_raw_bear = self.tide_broke_above and self.tide_inrange_closes == i.tide_confirm_bars
        tide_regime_risky_bull = rate_regime_str == "STRONG TREND" and not rate_bull
        tide_regime_risky_bear = rate_regime_str == "STRONG TREND" and rate_bull
        _tide_conflicts_bull = rate_qty_open > 0 and not rate_pos_long
        _tide_conflicts_bear = rate_qty_open > 0 and rate_pos_long
        if i.tide_confirm_mode == "Strict":
            _tide_confirmed_l, _tide_confirmed_s = rej_cluster_bull_confirmed, rej_cluster_bear_confirmed
        elif i.tide_confirm_mode == "Balanced":
            _tide_confirmed_l = rej_cluster_bull and _delivery_shift_recent_bull
            _tide_confirmed_s = rej_cluster_bear and _delivery_shift_recent_bear
        else:
            _tide_confirmed_l = rej_cluster_bull or cisd_bull or choch_bull
            _tide_confirmed_s = rej_cluster_bear or cisd_bear or choch_bear
        tide_signal_bull = i.use_tide and tide_return_raw_bull and _tide_confirmed_l and (not i.use_tide_regime_filter or not tide_regime_risky_bull) and not _tide_conflicts_bull and h4_qty_open == 0
        tide_signal_bear = i.use_tide and tide_return_raw_bear and _tide_confirmed_s and (not i.use_tide_regime_filter or not tide_regime_risky_bear) and not _tide_conflicts_bear and h4_qty_open == 0
        smc_ob_ote_l = ob_in_fresh_bull or pd_ote_long; smc_ob_ote_s = ob_in_fresh_bear or pd_ote_short
        smc_confluence_bull = (choch_bull or bos_bull) and self.sweep_bars_since_lo <= i.smc_confirm_window and smc_ob_ote_l
        smc_confluence_bear = (choch_bear or bos_bear) and self.sweep_bars_since_hi <= i.smc_confirm_window and smc_ob_ote_s
        # volume delta exhaustion
        _vd_range = _h - _l
        vol_delta = ((((_c - _l) / _vd_range) * volume) - (((_h - _c) / _vd_range) * volume)) if _vd_range > 0.0 else 0.0
        vd_vol_spike = volume > self.vd_vol_sma.update(volume) * i.vd_spike_mult
        _vd_c_high_prev = self.vd_c_hi.update(_c); _vd_c_low_prev = self.vd_c_lo.update(_c)
        _vd_delta_high_prev = self.vd_d_hi.update(vol_delta); _vd_delta_low_prev = self.vd_d_lo.update(vol_delta)
        _vd_c_high_prev_1, _vd_c_low_prev_1, _vd_delta_high_prev_1, _vd_delta_low_prev_1 = self._p_vd
        self._p_vd = (_vd_c_high_prev, _vd_c_low_prev, _vd_delta_high_prev, _vd_delta_low_prev)
        vd_bull_exhaustion = i.use_vol_delta and _c >= _vd_c_high_prev_1 and vol_delta < _vd_delta_high_prev_1 and vd_vol_spike
        vd_bear_exhaustion = i.use_vol_delta and _c <= _vd_c_low_prev_1 and vol_delta > _vd_delta_low_prev_1 and vd_vol_spike

        # ── time-of-day + empirical percentile ──
        _tod_hour_now = ny_h
        _tod_wr = 0.5; _tod_n = 0
        if i.use_tod_tracking and 0 <= _tod_hour_now <= 23:
            _w = self.tod_wins[_tod_hour_now]; _lo = self.tod_losses[_tod_hour_now]
            _tod_n = _w + _lo; _tod_wr = float(_w) / float(_tod_n) if _tod_n > 0 else 0.5
        tod_hour_ok = (not i.use_tod_filter) or _tod_n < i.tod_min_sample or _tod_wr >= i.tod_min_winrate

        def f_emp_pctile(buf: List[float], holdout: int) -> float:
            _usable = max(0, len(buf) - holdout)
            if _usable >= i.emp_min_obs:
                _sorted = sorted(buf[:_usable])
                _idx = int(pround((i.emp_percentile / 100.0) * (len(_sorted) - 1)))
                return max(i.emp_min_pct, min(i.emp_max_pct, _sorted[_idx]))
            return NAN
        _emp_regime_trending = rate_regime_str in ("STRONG TREND", "WEAK TREND", "EMERGING")
        emp_tp1_pct = NAN
        if i.use_empirical_tp:
            _emp_regime_specific = f_emp_pctile(self.emp_buf_trend if _emp_regime_trending else self.emp_buf_chop, i.emp_holdout_recent) if i.use_emp_regime_split else NAN
            _emp_pooled = f_emp_pctile(self.emp_mfe_pct_buf, i.emp_holdout_recent)
            emp_tp1_pct = _emp_regime_specific if not na(_emp_regime_specific) else _emp_pooled

        # ── §10 confluence gate ──
        rsi_long_ok = ftr_val > ftr_sig and ftr_val > 0.0 and rsi_slope > -2.0
        rsi_short_ok = ftr_val < ftr_sig and ftr_val < 0.0 and rsi_slope < 2.0
        above_vwap = _c > vwap_val; below_vwap = _c < vwap_val
        _cr = _h - _l
        bull_conv = _c > _o and _cr > 0.0 and abs(_c - _o) / _cr >= 0.50
        bear_conv = _c < _o and _cr > 0.0 and abs(_c - _o) / _cr >= 0.50
        vol_surge = volume > vol_ma * 1.3

        def f_vote_wt(idx: int) -> float:
            hf = self.v_hits[idx]; mf = self.v_misses[idx]; hn = self.v_hits_nf[idx]; mn = self.v_misses_nf[idx]
            nf = hf + mf; nn = hn + mn
            acc_fired = float(hf) / float(nf) if nf > 0 else 0.5
            acc_notfired = float(hn) / float(nn) if nn > 0 else 0.5
            _wt = 1.0
            if i.use_adaptive_weights and nf >= 10 and nn >= 10:
                _wt = max(0.0, min(2.0, 1.0 + (acc_fired - acc_notfired) * 4.0))
            elif i.use_adaptive_weights and nf >= 10:
                _wt = max(0.0, min(2.0, 0.75 + (acc_fired - 0.5) * 1.0))
            return _wt
        wts = [f_vote_wt(k) for k in range(8)]
        wts.append(f_vote_wt(8) if i.use_kalman else 0.0)
        wts.append(f_vote_wt(9) if i.use_pma else 0.0)
        wts.append(f_vote_wt(10) if i.use_pe else 0.0)
        wts.append(f_vote_wt(11) if i.use_cc else 0.0)
        total_weight = sum(wts)
        active_votes = sum(1 for w_ in wts if w_ > 0.1)
        avg_weight = total_weight / float(active_votes) if active_votes > 0 else 1.0
        votes_l = [mtf_long, rsi_long_ok, above_vwap, bull_conv, vol_surge, regime_accel, cci_long, xgb_long_ok, kf_long_ok, pma_long_ok, pe_long_ok, cc_long_ok]
        votes_s = [mtf_short, rsi_short_ok, below_vwap, bear_conv, vol_surge, regime_accel, cci_short, xgb_short_ok, kf_short_ok, pma_short_ok, pe_short_ok, cc_short_ok]
        raw_l = sum(wts[k] for k in range(12) if votes_l[k]); raw_s = sum(wts[k] for k in range(12) if votes_s[k])
        cyc_mod_l = (avg_weight if cycle_rising else -avg_weight) if (i.use_cycle and in_sess) else 0.0
        cyc_mod_s = (avg_weight if cycle_falling else -avg_weight) if (i.use_cycle and in_sess) else 0.0
        adj_l = raw_l + cyc_mod_l; adj_s = raw_s + cyc_mod_s
        sess_mod_l = ((1.0 if sess_bias_dir == 1 else -1.0) * i.sess_bias_weight * sess_bias_str * avg_weight) if (i.use_session_bias and _in_rth_v3 and sess_bias_dir != 0) else 0.0
        sess_mod_s = ((1.0 if sess_bias_dir == -1 else -1.0) * i.sess_bias_weight * sess_bias_str * avg_weight) if (i.use_session_bias and _in_rth_v3 and sess_bias_dir != 0) else 0.0
        hb_mod_l = float(hb_timing_l) * i.hour_breach_weight * avg_weight if (i.use_hour_breach and self.hr_open_inside) else 0.0
        hb_mod_s = float(hb_timing_s) * i.hour_breach_weight * avg_weight if (i.use_hour_breach and self.hr_open_inside) else 0.0
        mid_mod = -0.5 * avg_weight if (i.midday_mode == "Penalize" and in_midday) else 0.0
        final_l = adj_l + mp_mod_l + sess_mod_l + hb_mod_l + mid_mod
        final_s = adj_s + mp_mod_s + sess_mod_s + hb_mod_s + mid_mod
        _vote_slots = 8 + int(i.use_kalman) + int(i.use_pma) + int(i.use_pe) + int(i.use_cc)
        _bt_frac = 0.70
        if rate_regime >= 0.65: _bt_frac = 0.40
        elif rate_regime >= 0.40: _bt_frac = 0.50
        elif rate_regime >= 0.25: _bt_frac = 0.60
        base_thresh = int(pround(_bt_frac * float(_vote_slots)))
        eff_thresh = float(i.conf_min_votes)
        if i.use_adaptive_threshold and active_votes > 0:
            eff_thresh = float(base_thresh) * (total_weight / float(active_votes))
        fam_trend_l = int(mtf_long) + int(above_vwap) + int(pma_long_ok)
        fam_momo_l = int(rsi_long_ok) + int(bull_conv) + int(cci_long) + int(kf_long_ok)
        fam_vol_l = int(vol_surge) + int(regime_accel); fam_stat_l = int(xgb_long_ok) + int(pe_long_ok); fam_cyc_l = int(cc_long_ok)
        families_l = int(fam_trend_l > 0) + int(fam_momo_l > 0) + int(fam_vol_l > 0) + int(fam_stat_l > 0) + int(fam_cyc_l > 0)
        fam_trend_s = int(mtf_short) + int(below_vwap) + int(pma_short_ok)
        fam_momo_s = int(rsi_short_ok) + int(bear_conv) + int(cci_short) + int(kf_short_ok)
        fam_vol_s = int(vol_surge) + int(regime_accel); fam_stat_s = int(xgb_short_ok) + int(pe_short_ok); fam_cyc_s = int(cc_short_ok)
        families_s = int(fam_trend_s > 0) + int(fam_momo_s > 0) + int(fam_vol_s > 0) + int(fam_stat_s > 0) + int(fam_cyc_s > 0)
        family_agree_l = i.use_family_confluence and families_l >= i.family_min_for_bonus
        family_agree_s = i.use_family_confluence and families_s >= i.family_min_for_bonus
        if trc_trending:
            eff_thresh *= 0.92
        if i.use_smc_enhance and (smc_confluence_bull or smc_confluence_bear):
            eff_thresh *= i.smc_enhance_discount
        if family_agree_l or family_agree_s:
            eff_thresh *= i.family_discount
        eff_thresh *= shock_mult
        gate_long = (final_l >= eff_thresh) if i.use_confluence else True
        gate_short = (final_s >= eff_thresh) if i.use_confluence else True
        conf_long = rate_armed_long and gate_long and in_sess and not diverge_veto_l and not (i.use_ltf_veto and ltf_fail_long)
        conf_short = rate_armed_short and gate_short and in_sess and not diverge_veto_s and not (i.use_ltf_veto and ltf_fail_short)

        # ── §11 filters ──
        _ny_day = ny_dayofmonth(ts)
        if nz(self.ny_day_change.update(_ny_day), 0) != 0:
            self.daily_pnl = 0.0
        _eod_mins = int(math.floor(float(i.eod_flat_hhmm) / 100.0)) * 60 + (i.eod_flat_hhmm % 100)
        ch_, cm_ = ny_hour_minute(time_close); _mins_close = ch_ * 60 + cm_
        _past_eod = i.use_eod_flat and _mins_close >= _eod_mins
        eod_trigger = _past_eod and not self._p_past_eod
        self._p_past_eod = _past_eod
        eod_block_now = _past_eod
        in_entry_window = (not i.use_entry_window) or in_session(ts, i.sess_entry_window)
        cooldown_ok = (not i.use_cooldown) or self.bars_since_stop >= i.cooldown_bars
        daily_loss_ok = (not i.use_max_loss) or self.daily_pnl > i.max_daily_loss
        event_ok = (not fomc_block) and (not hv_block)
        entry_allowed = in_sess and in_entry_window and not eod_block_now and cooldown_ok and daily_loss_ok and tod_hour_ok and event_ok and not midday_block and not self.paused

        # ── §12.1 exit-distance model ──
        _tp1_dist_l = i.tp1_pts; _tp2_dist_l = i.tp2_pts; _sl_dist_l = i.sl_pts
        _tp1_dist_s = i.tp1_pts; _tp2_dist_s = i.tp2_pts; _sl_dist_s = i.sl_pts
        if i.tpsl_mode == "ATR-Based":
            _tp1_dist_l = i.tp1_atr_mult * atr14; _tp2_dist_l = i.tp2_atr_mult * atr14; _sl_dist_l = i.sl_atr_mult * atr14
            _tp1_dist_s, _tp2_dist_s, _sl_dist_s = _tp1_dist_l, _tp2_dist_l, _sl_dist_l
        elif i.tpsl_mode == "Percentage-Based":
            _tp1_dist_l = _c * i.tp1_pct / 100.0; _tp2_dist_l = _c * i.tp2_pct / 100.0; _sl_dist_l = _c * i.sl_pct / 100.0
            _tp1_dist_s, _tp2_dist_s, _sl_dist_s = _tp1_dist_l, _tp2_dist_l, _sl_dist_l
        elif i.tpsl_mode == "Structure-Based" and not na(struct_sh) and not na(struct_sl) and struct_sh > struct_sl:
            _struct_range = struct_sh - struct_sl
            _d_sh_l = struct_sh - _c
            _tp1_dist_l = _d_sh_l if _d_sh_l >= i.tp1_pts * 0.5 else i.tp1_pts
            _tp2_dist_l = _d_sh_l + _struct_range * i.struct_tp2_ext_mult
            _d_sl_l = _c - (struct_sl - i.struct_sl_buffer_atr * atr14)
            _sl_dist_l = _d_sl_l if (_d_sl_l > 0.0 and _d_sl_l <= i.sl_pts * 2.0) else i.sl_pts
            _d_sl_s = _c - struct_sl
            _tp1_dist_s = _d_sl_s if _d_sl_s >= i.tp1_pts * 0.5 else i.tp1_pts
            _tp2_dist_s = _d_sl_s + _struct_range * i.struct_tp2_ext_mult
            _d_sh_s = (struct_sh + i.struct_sl_buffer_atr * atr14) - _c
            _sl_dist_s = _d_sh_s if (_d_sh_s > 0.0 and _d_sh_s <= i.sl_pts * 2.0) else i.sl_pts
        if not na(emp_tp1_pct):
            _tp1_dist_l = _c * emp_tp1_pct / 100.0; _tp1_dist_s = _c * emp_tp1_pct / 100.0
        _tp1_dist_l = pmax(_tp1_dist_l, mintick); _tp2_dist_l = pmax(_tp2_dist_l, _tp1_dist_l + mintick); _sl_dist_l = pmax(_sl_dist_l, mintick)
        _tp1_dist_s = pmax(_tp1_dist_s, mintick); _tp2_dist_s = pmax(_tp2_dist_s, _tp1_dist_s + mintick); _sl_dist_s = pmax(_sl_dist_s, mintick)
        full_qty = i.qty_contracts

        # ── §12.2 per-trade frozen state ──
        if self.rate_pend_dir != 0 and rate_qty_open > 0:
            self.rate_pend_dir = 0
        _rate_went_flat = rate_qty_open == 0 and self.rate_pend_dir == 0 and self._emp_was_open
        _rate_new_trade = rate_qty_open > 0 and (na(self._emp_entry_bar) or rate_entry_bar != self._emp_entry_bar)
        _rate_trade_ended = _rate_went_flat or (_rate_new_trade and self._emp_was_open)
        if _rate_trade_ended and not na(self.rate_best_price) and not na(self._emp_ref_price) and self._emp_ref_price > 0.0:
            _mfe_pct = ((self.rate_best_price - self._emp_ref_price) / self._emp_ref_price * 100.0) if self._emp_was_long else ((self._emp_ref_price - self.rate_best_price) / self._emp_ref_price * 100.0)
            self.emp_mfe_pct_buf.append(_mfe_pct)
            if len(self.emp_mfe_pct_buf) > i.emp_window: self.emp_mfe_pct_buf.pop(0)
            if _emp_regime_trending:
                self.emp_buf_trend.append(_mfe_pct)
                if len(self.emp_buf_trend) > i.emp_window: self.emp_buf_trend.pop(0)
            else:
                self.emp_buf_chop.append(_mfe_pct)
                if len(self.emp_buf_chop) > i.emp_window: self.emp_buf_chop.pop(0)
        if _rate_went_flat or _rate_new_trade:
            self.rate_tp1_done = False; self.rate_best_price = NAN; self.trail_stop_long = NAN; self.trail_stop_short = NAN
            self.rate_be_armed = False; self.rate_tp1_bar = NAN
        if rate_qty_open == 0:
            self._emp_was_open = False; self._emp_entry_bar = NAN
        else:
            if rate_pos_long:
                self.rate_best_price = _c if na(self.rate_best_price) else max(self.rate_best_price, _c)
            else:
                self.rate_best_price = _c if na(self.rate_best_price) else min(self.rate_best_price, _c)
            self._emp_was_open = True; self._emp_was_long = rate_pos_long
            self._emp_ref_price = rate_avg_price; self._emp_entry_bar = rate_entry_bar
            if rate_qty_open < self.rate_qty_plan:
                self.rate_tp1_done = True
        if h4_qty_open == 0:
            self.tide_tp1_done = False
        elif h4_qty_open < i.tide_qty:
            self.tide_tp1_done = True
        rate_bars_in_trade = (bar_index - rate_entry_bar) if (rate_qty_open > 0 and not na(rate_entry_bar)) else 0

        # ── PULSE (conviction) ──
        _pulse_conf_l = min(1.0, final_l / eff_thresh) if eff_thresh > 0.0 else 0.0
        _pulse_conf_s = min(1.0, final_s / eff_thresh) if eff_thresh > 0.0 else 0.0
        _mag_regime = min(1.0, max(0.0, nz(rate_regime)))
        _mag_hurst = min(1.0, max(0.0, (nz(hurst) - 0.40) / 0.20))
        _mag_fdi = min(1.0, max(0.0, (1.50 - nz(fdi, 1.5)) / 0.40))
        _mag_trc = 1.0 if trc_trending else 0.0
        _mag_volexp = min(1.0, max(0.0, (nz(rate_vol_ratio, 1.0) - 0.80) / 0.70))
        _mag_accel = 1.0 if regime_accel else 0.0
        _mag_po3dist = 1.0 if po3_state == "DISTRIBUTION" else 0.5 if po3_state == "MANIPULATION" else 0.0
        _mag_mama = min(1.0, abs(nz(mama_spread, 0.0)) / atr14)
        _mag_kfvel = min(1.0, abs(nz(kf_vel, 0.0)) / (atr14 * 0.5))
        _mag_shared = _mag_regime * 0.12 + _mag_hurst * 0.08 + _mag_fdi * 0.05 + _mag_trc * 0.05 + _mag_volexp * 0.12 + _mag_accel * 0.08 + _mag_mama * 0.08 + _mag_kfvel * 0.07
        _mag_raw_l = _mag_shared + _mag_po3dist * 0.07 + (1.0 if expansion_confirmed_bull else 0.0) * 0.08 + (1.0 if self.struct_seq_bull else 0.0) * 0.05 + (1.0 if bos_bull else 0.0) * 0.05 + (htf_bull_count5 / 5.0) * 0.10
        _mag_raw_s = _mag_shared + _mag_po3dist * 0.07 + (1.0 if expansion_confirmed_bear else 0.0) * 0.08 + (1.0 if self.struct_seq_bear else 0.0) * 0.05 + (1.0 if bos_bear else 0.0) * 0.05 + (htf_bear_count5 / 5.0) * 0.10
        _mag_l = max(0.10, min(1.0, _mag_raw_l * (0.65 if vd_bull_exhaustion else 1.0)))
        _mag_s = max(0.10, min(1.0, _mag_raw_s * (0.65 if vd_bear_exhaustion else 1.0)))
        _pw = i.pulse_conf_weight
        _pulse_l = (max(_pulse_conf_l, 0.0001) ** _pw) * (_mag_l ** (1.0 - _pw))
        _pulse_s = (max(_pulse_conf_s, 0.0001) ** _pw) * (_mag_s ** (1.0 - _pw))
        _pulse_peak = max(_pulse_l, _pulse_s)
        _pulse_state = "DORMANT"
        if _pulse_peak >= 0.90: _pulse_state = "IGNITION"
        elif _pulse_peak >= 0.75: _pulse_state = "CRITICAL"
        elif _pulse_peak >= 0.50: _pulse_state = "CHARGED"
        elif _pulse_peak >= 0.25: _pulse_state = "BUILDING"

        # ── sizing ──
        def f_conv_qty(conviction: float) -> int:
            _span = max(i.conv_ceiling - i.conv_floor, 0.01)
            _norm = min(1.0, max(0.0, (conviction - i.conv_floor) / _span))
            _mult = i.conv_min_mult + (1.0 - i.conv_min_mult) * _norm
            _q = int(max(1, pround(float(i.qty_contracts) * _mult)))
            return min(_q, i.qty_contracts)
        _vol_pct = self.vol_pct_rank.update(atr14)
        _vol_mult = (1.0 if _vol_pct >= 66.67 else i.vol_mid_mult if _vol_pct >= 33.33 else i.vol_low_mult) if i.size_mode == "Vol-regime tercile" else 1.0
        if i.size_mode == "Risk-$ per trade":
            _risk_qty_l = int(max(1.0, math.floor(i.risk_usd_per_trade / max(_sl_dist_l * i.point_value, mintick * i.point_value)))) if not na(_sl_dist_l) else full_qty
            _risk_qty_s = int(max(1.0, math.floor(i.risk_usd_per_trade / max(_sl_dist_s * i.point_value, mintick * i.point_value)))) if not na(_sl_dist_s) else full_qty
        else:
            _risk_qty_l = full_qty; _risk_qty_s = full_qty
        _conv_mult_l = float(f_conv_qty(_pulse_l)) / float(i.qty_contracts) if i.use_conviction_sizing else 1.0
        _conv_mult_s = float(f_conv_qty(_pulse_s)) / float(i.qty_contracts) if i.use_conviction_sizing else 1.0
        rate_qty_long = int(max(1.0, min(float(i.qty_contracts), pround(float(min(_risk_qty_l, i.qty_contracts)) * _conv_mult_l * _vol_mult))))
        rate_qty_short = int(max(1.0, min(float(i.qty_contracts), pround(float(min(_risk_qty_s, i.qty_contracts)) * _conv_mult_s * _vol_mult))))

        # ── §12.3 / 12.4 adaptive-weight bookkeeping + closed-trade scan ──
        def f_w_retire_slot(slot: int) -> None:
            old_oc = self.w_outcome[slot]
            if old_oc != 0:
                for vi in range(12):
                    if self.snap[vi][slot] != 0:
                        if old_oc == 1: self.v_hits[vi] = max(0, self.v_hits[vi] - 1)
                        else: self.v_misses[vi] = max(0, self.v_misses[vi] - 1)
                    else:
                        if old_oc == 1: self.v_hits_nf[vi] = max(0, self.v_hits_nf[vi] - 1)
                        else: self.v_misses_nf[vi] = max(0, self.v_misses_nf[vi] - 1)
            self.w_outcome[slot] = 0

        def f_w_record(slot: int, outcome: int) -> None:
            self.w_outcome[slot] = outcome
            for vi in range(12):
                if self.snap[vi][slot] != 0:
                    if outcome == 1: self.v_hits[vi] += 1
                    else: self.v_misses[vi] += 1
                else:
                    if outcome == 1: self.v_hits_nf[vi] += 1
                    else: self.v_misses_nf[vi] += 1

        closed_now: List[Dict[str, Any]] = []
        if len(em.closed) > self._prev_closed:
            for ci in range(self._prev_closed, len(em.closed)):
                ct = em.closed[ci]
                _ceid, _ccom, _cpnl, _ceb = ct.entry_id, ct.exit_comment, ct.profit, ct.entry_bar
                closed_now.append({"id": _ceid, "comment": _ccom, "profit": _cpnl, "qty": ct.qty, "exit": ct.exit_price})
                if _ceid in ("Long", "Short"):
                    if _ccom in ("L_TP1", "S_TP1"):
                        self.rate_tp1_done = True
                    if _ccom in ("L_SL", "S_SL"):
                        self.bars_since_stop = 0
                    if _ceb != self.w_last_rec_entry_bar:
                        self.w_last_rec_entry_bar = _ceb
                        _outcome = 1 if _cpnl >= 0.0 else -1
                        if self.w_slot_queue:
                            f_w_record(self.w_slot_queue.pop(0), _outcome)
                        if self.tod_hour_queue:
                            _th = self.tod_hour_queue.pop(0)
                            if i.use_tod_tracking and 0 <= _th <= 23:
                                if _outcome == 1: self.tod_wins[_th] += 1
                                else: self.tod_losses[_th] += 1
                elif _ceid in ("TideLong", "TideShort"):
                    if _ccom == "T_TP1":
                        self.tide_tp1_done = True
        self._prev_closed = len(em.closed)

        # ── §12.5 pending pullback-limit management ──
        if self.rate_pend_dir != 0:
            _pid = "Long" if self.rate_pend_dir == 1 else "Short"
            _pend_stale = (bar_index - self.rate_pend_bar) >= i.pullback_max_bars
            _pend_invalid = (self.rate_pend_dir == 1 and not rate_bull) or (self.rate_pend_dir == -1 and rate_bull) or eod_block_now
            if _pend_invalid or (_pend_stale and not (i.pullback_fallback and entry_allowed)):
                for cid in (_pid, "L1", "L2", "S1", "S2"):
                    em.cancel(cid)
                if self.w_slot_queue: self.w_slot_queue.pop()
                if self.tod_hour_queue: self.tod_hour_queue.pop()
                self.rate_pend_dir = 0
            elif _pend_stale:
                if self.rate_pend_dir == 1:
                    em.entry("Long", 1, self.rate_qty_plan, comment="PB→MKT")
                else:
                    em.entry("Short", -1, self.rate_qty_plan, comment="PB→MKT")
                self.rate_pend_dir = 0

        # ── §12.6 entry decision ──
        _rev_long_to_short = i.use_flip_exit and rate_qty_open > 0 and rate_pos_long
        _rev_short_to_long = i.use_flip_exit and rate_qty_open > 0 and not rate_pos_long
        enter_long_now = conf_long and entry_allowed and self.rate_pend_dir == 0 and (rate_qty_open == 0 or _rev_short_to_long)
        enter_short_now = conf_short and entry_allowed and self.rate_pend_dir == 0 and (rate_qty_open == 0 or _rev_long_to_short) and not enter_long_now

        def _snapshot(votes: List[bool]) -> None:
            if self.w_trade_count >= 50:
                f_w_retire_slot(self.w_write_ptr)
            self.w_outcome[self.w_write_ptr] = 0
            for vi in range(12):
                self.snap[vi][self.w_write_ptr] = 1 if votes[vi] else 0
            self.w_slot_queue.append(self.w_write_ptr); self.tod_hour_queue.append(_tod_hour_now)
            self.w_write_ptr = (self.w_write_ptr + 1) % 50; self.w_trade_count += 1

        if enter_long_now:
            _snapshot(votes_l)
            if h4_qty_open > 0 and not h4_pos_long:
                em.close("TideShort", comment="T_REV")
            _q = rate_qty_long
            _q1 = _q if _q <= 1 else int(max(1.0, min(float(_q - 1), math.floor(float(_q) * float(i.tp1_split_pct) / 100.0))))
            _q2 = _q - _q1
            _pb = i.use_pullback_entry and rate_qty_open == 0
            if _pb:
                em.entry("Long", 1, _q, limit=_c - atr14 * i.pullback_atr)
                self.rate_pend_dir = 1; self.rate_pend_bar = bar_index
            else:
                em.entry("Long", 1, _q)
            em.exit("L1", "Long", qty=_q1, profit=_tp1_dist_l / mintick, loss=_sl_dist_l / mintick, comment_profit="L_TP1", comment_loss="L_SL")
            if _q2 > 0:
                em.exit("L2", "Long", qty=_q2, profit=_tp2_dist_l / mintick, loss=_sl_dist_l / mintick, comment_profit="L_TP2", comment_loss="L_SL")
            self.rate_tp1_dist, self.rate_tp2_dist, self.rate_sl_dist = _tp1_dist_l, _tp2_dist_l, _sl_dist_l
            self.rate_qty_plan = _q; self.rate_tp1_done = False; self.rate_sig_price = _c; self.rate_best_price = NAN
            self.trail_stop_long = NAN; self.trail_stop_short = NAN; self.rate_be_armed = False; self.rate_tp1_bar = NAN
            self.rate_flip_used = True; self.bars_since_stop = 999
            self.events.append({"ts": ts, "bar": bar_index, "kind": "signal", "text": f"RATE LONG signal x{_q} (tp1 {_tp1_dist_l:.4g} tp2 {_tp2_dist_l:.4g} sl {_sl_dist_l:.4g}) score {final_l:.2f}/{eff_thresh:.2f}"})
        if enter_short_now:
            _snapshot(votes_s)
            if h4_qty_open > 0 and h4_pos_long:
                em.close("TideLong", comment="T_REV")
            _q = rate_qty_short
            _q1 = _q if _q <= 1 else int(max(1.0, min(float(_q - 1), math.floor(float(_q) * float(i.tp1_split_pct) / 100.0))))
            _q2 = _q - _q1
            _pb = i.use_pullback_entry and rate_qty_open == 0
            if _pb:
                em.entry("Short", -1, _q, limit=_c + atr14 * i.pullback_atr)
                self.rate_pend_dir = -1; self.rate_pend_bar = bar_index
            else:
                em.entry("Short", -1, _q)
            em.exit("S1", "Short", qty=_q1, profit=_tp1_dist_s / mintick, loss=_sl_dist_s / mintick, comment_profit="S_TP1", comment_loss="S_SL")
            if _q2 > 0:
                em.exit("S2", "Short", qty=_q2, profit=_tp2_dist_s / mintick, loss=_sl_dist_s / mintick, comment_profit="S_TP2", comment_loss="S_SL")
            self.rate_tp1_dist, self.rate_tp2_dist, self.rate_sl_dist = _tp1_dist_s, _tp2_dist_s, _sl_dist_s
            self.rate_qty_plan = _q; self.rate_tp1_done = False; self.rate_sig_price = _c; self.rate_best_price = NAN
            self.trail_stop_long = NAN; self.trail_stop_short = NAN; self.rate_be_armed = False; self.rate_tp1_bar = NAN
            self.rate_flip_used = True; self.bars_since_stop = 999
            self.events.append({"ts": ts, "bar": bar_index, "kind": "signal", "text": f"RATE SHORT signal x{_q} (tp1 {_tp1_dist_s:.4g} tp2 {_tp2_dist_s:.4g} sl {_sl_dist_s:.4g}) score {final_s:.2f}/{eff_thresh:.2f}"})

        # ── §12.7 runner management (after TP1) ──
        _ltf_health = (nz(ltf_2m_regime, 0.5) + nz(ltf_5m_regime, 0.5)) / 2.0
        _trail_tighten_ltf = i.ltf_tighten_mult if (i.use_ltf_trail_tighten and _ltf_health < i.ltf_weak_thresh) else 1.0
        _trail_tighten_vd = i.ltf_tighten_mult if ((rate_pos_long and vd_bull_exhaustion) or ((not rate_pos_long) and vd_bear_exhaustion)) else 1.0
        _trail_tighten = _trail_tighten_ltf * _trail_tighten_vd
        _trail_atr_dist = atr14 * i.trail_atr_mult * _trail_tighten
        if i.use_trailing_tp2 and rate_qty_open > 0 and self.rate_tp1_done:
            if rate_pos_long:
                _cand_atr = _c - _trail_atr_dist
                _cand_kf = (kf_level - atr14 * i.trail_kf_buffer_atr) if not na(kf_level) else _cand_atr
                _cand = max(_cand_atr, _cand_kf)
                self.trail_stop_long = _cand if na(self.trail_stop_long) else max(self.trail_stop_long, _cand)
            else:
                _cand_atr = _c + _trail_atr_dist
                _cand_kf = (kf_level + atr14 * i.trail_kf_buffer_atr) if not na(kf_level) else _cand_atr
                _cand = min(_cand_atr, _cand_kf)
                self.trail_stop_short = _cand if na(self.trail_stop_short) else min(self.trail_stop_short, _cand)
        if rate_qty_open > 0 and self.rate_tp1_done and na(self.rate_tp1_bar):
            self.rate_tp1_bar = bar_index
        rate_runner_stop = NAN; rate_runner_tag = ""; rate_weak_now = False
        if rate_qty_open > 0 and self.rate_tp1_done and not na(rate_avg_price):
            _bars_since_tp1 = 0 if na(self.rate_tp1_bar) else bar_index - self.rate_tp1_bar
            _tp1_lvl = rate_avg_price + self.rate_tp1_dist if rate_pos_long else rate_avg_price - self.rate_tp1_dist
            _ext_best = 0.0 if na(self.rate_best_price) else ((self.rate_best_price - _tp1_lvl) if rate_pos_long else (_tp1_lvl - self.rate_best_price))
            rate_weak_now = rate_regime < i.runner_weak_regime or (i.use_ltf_trail_tighten and _ltf_health < i.ltf_weak_thresh) or (rate_pos_long and vd_bull_exhaustion) or ((not rate_pos_long) and vd_bear_exhaustion)
            _delay_ok = _bars_since_tp1 >= i.be_delay_bars and _ext_best >= atr14 * i.be_extend_atr
            _arm_now = i.runner_mode == "Immediate BE (v2)" or (i.runner_mode == "Net-BE → Delayed BE" and (_delay_ok or (i.runner_weak_be and rate_weak_now)))
            if _arm_now:
                self.rate_be_armed = True
            _q_closed = max(self.rate_qty_plan - rate_qty_open, 1)
            _net_be_dist = float(_q_closed) * self.rate_tp1_dist / float(rate_qty_open)
            if rate_pos_long:
                _stop = rate_avg_price - self.rate_sl_dist; rate_runner_tag = "L_SL"
                if i.runner_mode != "Original SL" and rate_avg_price - _net_be_dist > _stop:
                    _stop = rate_avg_price - _net_be_dist; rate_runner_tag = "L_NETBE"
                if self.rate_be_armed and rate_avg_price + i.be_offset_pts > _stop:
                    _stop = rate_avg_price + i.be_offset_pts; rate_runner_tag = "L_BE"
                if i.use_trailing_tp2 and not na(self.trail_stop_long) and self.trail_stop_long > _stop:
                    _stop = self.trail_stop_long; rate_runner_tag = "L_TRAIL"
                rate_runner_stop = _stop
                em.exit("L2", "Long", qty=rate_qty_open, limit=rate_avg_price + self.rate_tp2_dist, stop=_stop, comment_profit="L_TP2", comment_loss=rate_runner_tag)
            else:
                _stop = rate_avg_price + self.rate_sl_dist; rate_runner_tag = "S_SL"
                if i.runner_mode != "Original SL" and rate_avg_price + _net_be_dist < _stop:
                    _stop = rate_avg_price + _net_be_dist; rate_runner_tag = "S_NETBE"
                if self.rate_be_armed and rate_avg_price - i.be_offset_pts < _stop:
                    _stop = rate_avg_price - i.be_offset_pts; rate_runner_tag = "S_BE"
                if i.use_trailing_tp2 and not na(self.trail_stop_short) and self.trail_stop_short < _stop:
                    _stop = self.trail_stop_short; rate_runner_tag = "S_TRAIL"
                rate_runner_stop = _stop
                em.exit("S2", "Short", qty=rate_qty_open, limit=rate_avg_price - self.rate_tp2_dist, stop=_stop, comment_profit="S_TP2", comment_loss=rate_runner_tag)

        # ── §12.8 discretionary exits ──
        rate_stagnant = i.use_stagnation_exit and rate_qty_open > 0 and not self.rate_tp1_done and rate_bars_in_trade >= i.stagnation_bars and not na(self.rate_best_price) and not na(rate_avg_price) and abs(self.rate_best_price - rate_avg_price) < atr14 * i.stagnation_min_atr
        rate_flip_exit_now = i.use_flip_exit and rate_qty_open > 0 and ((rate_pos_long and not rate_bull) or ((not rate_pos_long) and rate_bull)) and not enter_long_now and not enter_short_now
        if rate_qty_open > 0:
            _rid = "Long" if rate_pos_long else "Short"; _rpre = "L_" if rate_pos_long else "S_"
            if eod_trigger:
                em.close(_rid, comment=_rpre + "EOD")
            elif rate_flip_exit_now:
                em.close(_rid, comment=_rpre + "FLIP")
            elif rate_stagnant:
                em.close(_rid, comment=_rpre + "STAG")
        tp1_price = (rate_avg_price + self.rate_tp1_dist if rate_pos_long else rate_avg_price - self.rate_tp1_dist) if (rate_qty_open > 0 and not self.rate_tp1_done) else NAN
        tp2_price = (rate_avg_price + self.rate_tp2_dist if rate_pos_long else rate_avg_price - self.rate_tp2_dist) if rate_qty_open > 0 else NAN
        if rate_qty_open > 0:
            sl_price = rate_runner_stop if (self.rate_tp1_done and not na(rate_runner_stop)) else (rate_avg_price - self.rate_sl_dist if rate_pos_long else rate_avg_price + self.rate_sl_dist)
        else:
            sl_price = NAN

        # ── §12.9 TIDE execution ──
        _tide_range = (tide_hi - tide_lo) if (not na(tide_hi) and not na(tide_lo)) else NAN
        _tide_mid_arith = (tide_hi + tide_lo) / 2.0 if (not na(tide_hi) and not na(tide_lo)) else NAN
        _tide_poc_ok = i.use_tide_poc_target and not na(mp_poc) and not na(tide_hi) and not na(tide_lo) and mp_poc > tide_lo and mp_poc < tide_hi
        tide_tp1_long = mp_poc if _tide_poc_ok else _tide_mid_arith
        tide_tp2_long = tide_hi + _tide_range * i.tide_ext_mult if not na(tide_hi) else NAN
        tide_sl_long = tide_lo - atr14 * 0.5 if not na(tide_lo) else NAN
        tide_tp1_short = tide_tp1_long
        tide_tp2_short = tide_lo - _tide_range * i.tide_ext_mult if not na(tide_lo) else NAN
        tide_sl_short = tide_hi + atr14 * 0.5 if not na(tide_hi) else NAN
        tide_q1 = i.tide_qty if i.tide_qty <= 1 else int(max(1.0, math.floor(float(i.tide_qty) / 2.0)))
        tide_q2 = i.tide_qty - tide_q1
        tide_enter_l = tide_signal_bull and not self.paused and h4_qty_open == 0 and not na(tide_tp1_long) and not na(tide_sl_long) and tide_tp1_long > _c and tide_sl_long < _c and not enter_short_now and self.rate_pend_dir != -1 and not (i.eod_flat_tide and eod_block_now)
        tide_enter_s = tide_signal_bear and not self.paused and h4_qty_open == 0 and not na(tide_tp1_short) and not na(tide_sl_short) and tide_tp1_short < _c and tide_sl_short > _c and not enter_long_now and self.rate_pend_dir != 1 and not (i.eod_flat_tide and eod_block_now)
        if tide_enter_l:
            em.entry("TideLong", 1, i.tide_qty)
            em.exit("T1", "TideLong", qty=tide_q1, limit=tide_tp1_long, stop=tide_sl_long, comment_profit="T_TP1", comment_loss="T_SL")
            if tide_q2 > 0:
                em.exit("T2", "TideLong", qty=tide_q2, limit=tide_tp2_long, stop=tide_sl_long, comment_profit="T_TP2", comment_loss="T_SL")
            self.tide_tp2_lvl = tide_tp2_long; self.tide_sl_lvl = tide_sl_long; self.tide_tp1_done = False
            self.events.append({"ts": ts, "bar": bar_index, "kind": "signal", "text": f"TIDE LONG signal x{i.tide_qty} (range {tide_lo:.4g}-{tide_hi:.4g})"})
        if tide_enter_s:
            em.entry("TideShort", -1, i.tide_qty)
            em.exit("T1", "TideShort", qty=tide_q1, limit=tide_tp1_short, stop=tide_sl_short, comment_profit="T_TP1", comment_loss="T_SL")
            if tide_q2 > 0:
                em.exit("T2", "TideShort", qty=tide_q2, limit=tide_tp2_short, stop=tide_sl_short, comment_profit="T_TP2", comment_loss="T_SL")
            self.tide_tp2_lvl = tide_tp2_short; self.tide_sl_lvl = tide_sl_short; self.tide_tp1_done = False
            self.events.append({"ts": ts, "bar": bar_index, "kind": "signal", "text": f"TIDE SHORT signal x{i.tide_qty} (range {tide_lo:.4g}-{tide_hi:.4g})"})
        if h4_qty_open > 0 and self.tide_tp1_done and i.tide_be_after_tp1 and not na(h4_avg_price) and not na(self.tide_sl_lvl) and not na(self.tide_tp2_lvl):
            if h4_pos_long:
                em.exit("T2", "TideLong", qty=h4_qty_open, limit=self.tide_tp2_lvl, stop=max(self.tide_sl_lvl, h4_avg_price + i.be_offset_pts), comment_profit="T_TP2", comment_loss="T_BE")
            else:
                em.exit("T2", "TideShort", qty=h4_qty_open, limit=self.tide_tp2_lvl, stop=min(self.tide_sl_lvl, h4_avg_price - i.be_offset_pts), comment_profit="T_TP2", comment_loss="T_BE")
        if i.eod_flat_tide and eod_trigger and h4_qty_open > 0:
            em.close("TideLong" if h4_pos_long else "TideShort", comment="T_EOD")

        # ── daily P&L / cooldown ──
        realized = em.netprofit - self._p_netprofit if not na(self._p_netprofit) else NAN
        self._p_netprofit = em.netprofit
        if not na(realized):
            self.daily_pnl += realized
        if rate_qty_open == 0 and self.rate_pend_dir == 0 and self.bars_since_stop < 999:
            self.bars_since_stop += 1

        # ── snapshot for the dashboard / journal ──
        s_exec = "flat"
        if rate_qty_open > 0:
            s_exec = ("LONG " if rate_pos_long else "SHORT ") + f"{rate_qty_open}/{self.rate_qty_plan}" + ((f"  runner->{rate_runner_tag}" + ("  armed" if self.rate_be_armed else "  weak" if rate_weak_now else "")) if self.rate_tp1_done else "  bracket") + f"  {rate_bars_in_trade}b"
        elif self.rate_pend_dir != 0:
            s_exec = ("PB-LIMIT long " if self.rate_pend_dir == 1 else "PB-LIMIT short ") + f"{bar_index - self.rate_pend_bar}/{i.pullback_max_bars}b"
        elif rate_armed_long:
            s_exec = f"ARMED L  {rate_bars_since_flip}/{i.arm_bars}b" + ("  gate ok" if gate_long else "  gate x")
        elif rate_armed_short:
            s_exec = f"ARMED S  {rate_bars_since_flip}/{i.arm_bars}b" + ("  gate ok" if gate_short else "  gate x")
        elif self.rate_flip_used:
            s_exec = f"flip used  {rate_bars_since_flip}b ago"
        if eod_block_now:
            s_exec += "  [EOD]"
        elif not entry_allowed:
            s_exec += "  [no-entry]"
        vote_names = ["MTF", "RSI", "VWAP", "Conv", "Vol", "Accel", "CCI", "XGB5", "Kalman", "MAMA", "PE", "Cycle"]
        self.state = {
            "ts": ts, "bar_index": bar_index, "o": _o, "h": _h, "l": _l, "c": _c, "v": volume,
            "rate_uptrend": rate_bull, "rate_st_line": self.rate_st_line, "rate_regime": rate_regime,
            "rate_regime_str": rate_regime_str, "hurst": hurst, "fdi": fdi, "rate_adx": rate_adx,
            "rate_atr_mult": rate_atr_mult, "atr14": atr14, "rate_long": rate_long, "rate_short": rate_short,
            "armed_long": rate_armed_long, "armed_short": rate_armed_short, "bars_since_flip": rate_bars_since_flip,
            "htf_dirs": list(htf_dirs), "htf_bull": htf_bull_count5, "htf_bear": htf_bear_count5,
            "ltf": [list(ltf[0]), list(ltf[1])],
            "votes": [{"name": vote_names[k], "l": bool(votes_l[k]), "s": bool(votes_s[k]), "w": round(wts[k], 3)} for k in range(12)],
            "final_l": final_l, "final_s": final_s, "eff_thresh": eff_thresh, "gate_long": gate_long, "gate_short": gate_short,
            "conf_long": conf_long, "conf_short": conf_short, "entry_allowed": entry_allowed, "in_session": in_sess,
            "diverge_veto_l": diverge_veto_l, "diverge_veto_s": diverge_veto_s,
            "cycle_rising": cycle_rising, "phase_deg": phase_deg, "vwap": vwap_val, "kf_level": kf_level, "kf_vel": kf_vel,
            "mama": mama_val, "fama": fama_val, "pe_norm": pe_norm, "trc": trc_trending, "po3": po3_state,
            "struct_sh": struct_sh, "struct_sl": struct_sl, "struct_bias": self.struct_bias, "pd_zone": pd_zone,
            "bos_bull": bos_bull, "bos_bear": bos_bear, "choch_bull": choch_bull, "choch_bear": choch_bear,
            "sweep_high": sweep_high, "sweep_low": sweep_low, "cisd_bull": cisd_bull, "cisd_bear": cisd_bear,
            "rej_cluster_bull": rej_cluster_bull, "rej_cluster_bear": rej_cluster_bear,
            "zones_d": [[t_, b_, sc] for t_, b_, sc in zip(self.d_top, self.d_bot, self.d_score)],
            "zones_s": [[t_, b_, sc] for t_, b_, sc in zip(self.s_top, self.s_bot, self.s_score)],
            "mp_poc": mp_poc, "mp_vah": mp_vah, "mp_val": mp_val,
            "tide_hi": tide_hi, "tide_lo": tide_lo, "tide_broke_above": self.tide_broke_above, "tide_broke_below": self.tide_broke_below,
            "tide_inrange_closes": self.tide_inrange_closes, "tide_signal_bull": tide_signal_bull, "tide_signal_bear": tide_signal_bear,
            "pulse_l": _pulse_l, "pulse_s": _pulse_s, "pulse_state": _pulse_state, "mag_l": _mag_l, "mag_s": _mag_s,
            "shock_mult": shock_mult, "families_l": families_l, "families_s": families_s,
            "rate_qty_open": rate_qty_open, "rate_pos_long": rate_pos_long, "rate_avg_price": rate_avg_price,
            "rate_qty_plan": self.rate_qty_plan, "rate_tp1_done": self.rate_tp1_done, "rate_be_armed": self.rate_be_armed,
            "runner_stop": rate_runner_stop, "runner_tag": rate_runner_tag, "tp1_price": tp1_price, "tp2_price": tp2_price, "sl_price": sl_price,
            "h4_qty_open": h4_qty_open, "h4_pos_long": h4_pos_long, "h4_avg_price": h4_avg_price,
            "tide_tp2_lvl": self.tide_tp2_lvl, "tide_sl_lvl": self.tide_sl_lvl,
            "enter_long_now": enter_long_now, "enter_short_now": enter_short_now, "tide_enter_l": tide_enter_l, "tide_enter_s": tide_enter_s,
            "exec": s_exec, "bars_since_stop": self.bars_since_stop, "daily_pnl": self.daily_pnl,
            "closed_now": closed_now, "tp1_dist": _tp1_dist_l, "sl_dist": _sl_dist_l, "tp2_dist": _tp2_dist_l,
            "w_trade_count": self.w_trade_count, "active_votes": active_votes, "avg_weight": avg_weight,
        }
        return self.state
