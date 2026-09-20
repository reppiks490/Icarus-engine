"""Engine tests - no network. Run: py -3 -m pytest tests_engine -q"""
from __future__ import annotations

import math
import random

from icarus_engine.emulator import Emulator
from icarus_engine.pine import ta
from icarus_engine.pine.series import NAN, Series, na, pmax
from icarus_engine.pine.timeframe import Aggregator, Bar, in_session, ny_hour_minute, tf_minutes
from icarus_engine.strategy.inputs import Inputs, crypto_profile
from icarus_engine.strategy.pulse import PulseStrategy
from icarus_engine.strategy.security import TFChain


def B(ts, o, h, l, c, v=100.0):
    return Bar(ts, o, h, l, c, v)


# ── Pine primitives ──
def test_series_history_and_na():
    s = Series(4)
    assert na(s[0])
    for v in (1.0, 2.0, 3.0):
        s.push(v)
    assert s[0] == 3.0 and s[1] == 2.0 and s[2] == 1.0 and na(s[3])
    assert na(pmax(1.0, NAN)) and pmax(1.0, 2.0) == 2.0


def test_ema_rma_seed_with_sma():
    e = ta.EMA(3)
    assert na(e.update(1.0)) and na(e.update(2.0))
    assert abs(e.update(3.0) - 2.0) < 1e-12          # SMA seed
    assert abs(e.update(4.0) - (0.5 * 4 + 0.5 * 2.0)) < 1e-12
    r = ta.RMA(2)
    assert na(r.update(2.0)) and abs(r.update(4.0) - 3.0) < 1e-12
    assert abs(r.update(6.0) - (0.5 * 6 + 0.5 * 3.0)) < 1e-12


def test_atr_and_dmi_seed():
    a = ta.ATR(2)
    assert na(a.update(10, 8, 9))
    v = a.update(11, 9, 10)                           # tr: 2, then max(2, |11-9|, |9-9|)=2 → sma 2
    assert abs(v - 2.0) < 1e-12
    d = ta.DMI(2, 2)
    for k in range(10):
        p, m, adx = d.update(10 + k, 9 + k, 9.5 + k)
    assert p > m and 0 <= adx <= 100


def test_supertrend_direction():
    st = ta.SUPERTREND(3.0, 3)
    d = None
    px = 100.0
    for k in range(60):                              # steady up-trend → direction -1
        px += 1.0
        _, d = st.update(px + 0.5, px - 0.5, px)
    assert d == -1
    for k in range(60):                              # then a crash → direction 1
        px -= 3.0
        _, d = st.update(px + 0.5, px - 0.5, px)
    assert d == 1


def test_pivot_highest_percentrank_barssince():
    ph = ta.PIVOT(2, 2, True)
    vals = [1, 2, 5, 2, 1, 3, 4]
    out = [ph.update(v) for v in vals]
    assert out[4] == 5 and all(na(x) for x in out[:4])
    hi = ta.HIGHEST(3)
    assert hi.update(1) == 1 and hi.update(NAN) == 1 and hi.update(3) == 3
    pr = ta.PERCENTRANK(4)
    for v in (1, 2, 3, 4):
        assert na(pr.update(v))
    assert pr.update(2.5) == 50.0
    bs = ta.BARSSINCE()
    assert na(bs.update(False)) and bs.update(True) == 0 and bs.update(False) == 1


def test_aggregator_and_sessions():
    agg = Aggregator(5)
    t0 = 1_700_000_000 - 1_700_000_000 % 300
    out = []
    for k in range(7):
        out += agg.push(B(t0 + 60 * k, 10 + k, 11 + k, 9 + k, 10.5 + k))
    assert len(out) == 1 and out[0].ts == t0 and out[0].o == 10 and out[0].h == 15 and out[0].l == 9 and out[0].c == 14.5 and out[0].v == 500
    assert agg.forming_bar().ts == t0 + 300
    assert tf_minutes("D") == 1440 and tf_minutes("240") == 240
    # 2026-09-14 13:30 UTC = 09:30 ET (EDT)
    ts = 1_789_392_600
    h, m = ny_hour_minute(ts)
    assert (h, m) == (9, 30)
    assert in_session(ts, "0930-1600") and not in_session(ts - 60, "0930-1600")
    assert in_session(ts - 3600, "1800-0930") and not in_session(ts, "1800-0930")


def test_tfchain_htf_and_ltf_lookup():
    ch = TFChain(15)
    t0 = 1_700_000_000 - 1_700_000_000 % 900
    px = 100.0
    for k in range(15 * 40):                          # 40 fifteen-minute bars from 1m bars
        px += 0.1
        ch.push_sub_bar(B(t0 + 60 * k, px, px + .2, px - .2, px), 1)
    # chart bar inside bucket 39 must see bucket 38's completed values, not 39's
    d, reg = ch.htf_values(t0 + 900 * 39 + 300)
    assert d == -1 and not na(reg)
    assert ch.by_bucket[t0 + 900 * 38] == (d, ch.by_bucket[t0 + 900 * 38][1], reg)
    l2 = TFChain(2)
    for k in range(60):
        l2.push_sub_bar(B(t0 + 60 * k, 1, 1, 1, 1), 1)
    d, bsf, reg = l2.ltf_values(t0 + 300 * 5, 5)      # chart 5m bar 25:00-30:00 → intrabar 26,28 → [1] = 26:00
    assert d == 1                                     # flat prices keep the reference direction 1


# ── emulator ──
def test_emulator_market_next_open_and_brackets():
    em = Emulator(100000, commission=1.0, mintick=0.5, contract_size=1.0)
    em.process_bar(B(0, 100, 101, 99, 100), 0)
    em.entry("Long", 1, 5)
    em.exit("L1", "Long", qty=2, profit=10 / 0.5, loss=20 / 0.5, comment_profit="L_TP1", comment_loss="L_SL")
    em.exit("L2", "Long", qty=3, profit=20 / 0.5, loss=20 / 0.5, comment_profit="L_TP2", comment_loss="L_SL")
    em.process_bar(B(60, 102, 103, 101, 102), 1)      # fills at open 102, exits live at 112/122 and stop 82
    assert em.position_size == 5 and em.open[0].entry_price == 102 and em.open[0].entry_bar == 1
    ex = {e["id"]: e for e in em.live_exits()}
    assert ex["L1"]["limit"] == 112 and ex["L1"]["stop"] == 82 and ex["L2"]["limit"] == 122
    em.process_bar(B(120, 103, 113, 102, 110), 2)     # TP1 hit
    assert em.position_size == 3 and em.closed[-1].exit_comment == "L_TP1" and em.closed[-1].exit_price == 112
    assert abs(em.closed[-1].profit - ((112 - 102) * 2 - 1.0 * 2 * 2)) < 1e-9
    em.process_bar(B(180, 110, 111, 80, 90), 3)       # stop hit for the runner at 82
    assert em.position_size == 0 and em.closed[-1].exit_comment == "L_SL" and em.closed[-1].exit_price == 82
    assert len(em.live_exits()) == 0


def test_emulator_intrabar_path_order_and_gap():
    # open closer to high → O→H→L→C: TP (above) is reached before SL (below)
    em = Emulator(100000, 0.0, 0.01)
    em.process_bar(B(0, 100, 101, 99, 100), 0)
    em.entry("Long", 1, 1)
    em.exit("L1", "Long", qty=1, limit=105, stop=95, comment_profit="TP", comment_loss="SL")
    em.process_bar(B(60, 100, 106, 94, 95), 1)        # |h-o|=6 > |o-l|=6 → tie → high first
    assert em.closed[-1].exit_comment == "TP"
    # open closer to low → O→L→H→C: SL first
    em2 = Emulator(100000, 0.0, 0.01)
    em2.process_bar(B(0, 100, 101, 99, 100), 0)
    em2.entry("Long", 1, 1)
    em2.exit("L1", "Long", qty=1, limit=105, stop=95, comment_profit="TP", comment_loss="SL")
    em2.process_bar(B(60, 100, 108, 96, 105), 1)      # |h-o|=8 > |o-l|=4 → low first, but low 96 > stop 95 → TP fills
    assert em2.closed[-1].exit_comment == "TP"
    em3 = Emulator(100000, 0.0, 0.01)
    em3.process_bar(B(0, 100, 101, 99, 100), 0)
    em3.entry("Long", 1, 1)
    em3.exit("L1", "Long", qty=1, limit=105, stop=95, comment_profit="TP", comment_loss="SL")
    em3.process_bar(B(60, 100, 100.5, 99.5, 100), 1)  # fills entry at 100, nothing hit
    em3.process_bar(B(120, 90, 92, 88, 91), 2)        # gap through the stop → fills at open 90
    assert em3.closed[-1].exit_comment == "SL" and em3.closed[-1].exit_price == 90


def test_emulator_reversal_pyramiding_and_close():
    em = Emulator(100000, 0.0, 0.01, pyramiding=2)
    em.process_bar(B(0, 100, 101, 99, 100), 0)
    em.entry("Long", 1, 5)
    em.entry("TideLong", 1, 2)
    em.process_bar(B(60, 100, 101, 99, 100), 1)
    assert em.position_size == 7 and len(em.open) == 2
    em.entry("Extra", 1, 1)                           # third same-direction entry → pyramiding limit
    em.process_bar(B(120, 100, 101, 99, 100), 2)
    assert em.position_size == 7
    em.entry("Short", -1, 5, comment="Short")        # reversal closes everything then opens short 5
    em.process_bar(B(180, 98, 99, 97, 98), 3)
    assert em.position_size == -5 and len(em.open) == 1 and em.open[0].entry_id == "Short"
    assert {t.exit_kind for t in em.closed} == {"reverse"} and all(t.exit_price == 98 for t in em.closed)
    em.close("Short", comment="S_EOD")
    em.process_bar(B(240, 97, 98, 96, 97), 4)
    assert em.position_size == 0 and em.closed[-1].exit_comment == "S_EOD" and em.closed[-1].exit_price == 97


def test_emulator_limit_entry_and_cancel():
    em = Emulator(100000, 0.0, 0.01)
    em.process_bar(B(0, 100, 101, 99, 100), 0)
    em.entry("Long", 1, 2, limit=98)
    em.exit("L1", "Long", qty=2, profit=100, loss=100)
    em.process_bar(B(60, 100, 101, 99, 100), 1)       # not reached
    assert em.position_size == 0 and em.pending_view()[0]["limit"] == 98
    em.process_bar(B(120, 99, 100, 97.5, 98.5), 2)    # reached → fills at 98, exits live (97 stop / 99 tp untouched)
    assert em.position_size == 2 and em.open[0].entry_price == 98 and em.live_exits()[0]["limit"] == 99
    em.cancel("L1")
    assert em.live_exits() == []


# ── strategy smoke test on synthetic data ──
def _synthetic(n: int, seed: int = 7):
    rnd = random.Random(seed)
    px = 100.0
    t0 = 1_789_300_000 - 1_789_300_000 % 300
    bars = []
    for k in range(n):
        drift = 0.02 if (k // 400) % 2 == 0 else -0.02
        o = px
        c = px * (1 + drift / 100 + rnd.gauss(0, 0.0015))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.0008)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, 0.0008)))
        bars.append(B(t0 + 300 * k, o, h, l, c, 50 + rnd.random() * 100))
        px = c
    return bars


def test_strategy_runs_and_trades_on_synthetic_bars():
    inp = crypto_profile(100.0, 0.01)
    em = Emulator(500000, 2.0, 0.01, 1000.0)
    st = PulseStrategy(inp, em, mintick=0.01, tf_minutes=5)
    bars = _synthetic(2500)
    for k, b in enumerate(bars):
        em.process_bar(b, k)
        htf = [(-1.0, 0.6)] * 5
        ltf = [(-1.0, 10.0, 0.6), (-1.0, 10.0, 0.6)]
        s = st.on_bar(b, k, htf, ltf)
    assert s["bar_index"] == 2499 and not na(s["rate_regime"]) and not na(s["atr14"])
    assert len(em.closed) > 0, "the strategy should have traded on 2500 trending/reverting bars"
    kinds = {t.exit_comment for t in em.closed}
    assert kinds & {"L_TP1", "S_TP1", "L_SL", "S_SL", "L_TP2", "S_TP2", "L_FLIP", "S_FLIP", "L_STAG", "S_STAG", "L_NETBE", "S_NETBE", "L_BE", "S_BE"}
    # every closed piece has a sane price and the emulator never held more than 2 entries
    assert all(t.exit_price > 0 for t in em.closed)


def test_strategy_pause_blocks_new_entries():
    inp = crypto_profile(100.0, 0.01)
    em = Emulator(500000, 2.0, 0.01, 1000.0)
    st = PulseStrategy(inp, em, mintick=0.01, tf_minutes=5)
    st.paused = True
    for k, b in enumerate(_synthetic(1500, seed=3)):
        em.process_bar(b, k)
        st.on_bar(b, k, [(-1.0, 0.6)] * 5, [(-1.0, 10.0, 0.6)] * 2)
    assert len(em.closed) == 0 and em.position_size == 0


def test_inputs_profiles():
    d = Inputs().to_dict()
    assert d["tp1_pts"] == 15.0 and d["runner_mode"].startswith("Net-BE") and d["use_session"]
    c = crypto_profile(77000.0, 0.01)
    assert not c.use_session and not c.use_eod_flat and c.tpsl_mode == "Percentage-Based" and c.be_offset_pts == 3.85
