"""Futures / multi-asset tests - no network."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
import time
from datetime import date, timedelta

import pytest

from icarus_engine.assets import parse_spec, resolve
from icarus_engine.calendar import CMECalendar, CryptoCalendar, _from_ny, _ny
from icarus_engine.contracts import ContractRoll, contract_months, last_completed_volume, third_friday, ticker_for
from icarus_engine.emulator import Emulator
from icarus_engine.feeds.yahoo import Yahoo
from icarus_engine.pine.series import na
from icarus_engine.pine.timeframe import Aggregator, Bar, tf_minutes
from icarus_engine.runtime import HeikinAshi, Journal, preset_path, resolve_inputs, validate_values
from icarus_engine.strategy.inputs import Inputs, crypto_profile
from icarus_engine.strategy.meta import inputs_from_tv_properties, load_meta, tv_value
from icarus_engine.strategy.pulse import PulseStrategy
from icarus_engine.strategy.security import TFChain


def B(ts, o, h, l, c, v=100.0):
    return Bar(ts, o, h, l, c, v)


def et(y, m, d, hh, mm=0):
    return _from_ny(y, m, d, hh, mm)


def hm(ts):
    return _ny(ts).strftime("%a %H:%M")


# 2026-09-14 (Monday). 13:10 UTC = 09:10 EDT.
MON_0910_ET = 1789391400


# ── calendar: Globex session, RTH chart session, alignment ──
def test_cme_globex_hours_and_trade_dates():
    c = CMECalendar(session="eth")
    assert c.is_open(MON_0910_ET)
    assert not c.is_open(et(2026, 9, 12, 9, 10))                                  # Saturday
    assert not c.is_open(et(2026, 9, 13, 17, 59)) and c.is_open(et(2026, 9, 13, 18, 0))   # Sunday open
    assert c.is_open(et(2026, 9, 18, 16, 59)) and not c.is_open(et(2026, 9, 18, 17, 0))   # Friday close
    assert not c.is_open(et(2026, 9, 14, 17, 30)) and c.is_open(et(2026, 9, 14, 18, 0))   # daily break
    assert c.session_id(MON_0910_ET) == "2026-09-14" and c.session_id(et(2026, 9, 14, 18, 0)) == "2026-09-15"
    assert c.next_open(et(2026, 9, 12, 9, 10)) == et(2026, 9, 13, 18, 0)
    assert "opens Sun 18:00 ET" in c.describe(et(2026, 9, 12, 9, 10))


def test_rth_chart_session_like_tradingview():
    r = CMECalendar(session="rth")
    assert r.anchor_et == "0930" and r.is_open(et(2026, 9, 14, 8, 0))               # Globex open ...
    assert not r.intraday_open(et(2026, 9, 14, 8, 0))                                # ... but no RTH bar before 09:30
    assert r.intraday_open(et(2026, 9, 14, 9, 30)) and r.intraday_open(et(2026, 9, 14, 16, 14))
    assert not r.intraday_open(et(2026, 9, 14, 16, 15)) and not r.intraday_open(et(2026, 9, 13, 20, 0))
    assert hm(r.bucket_start(MON_0910_ET, 20)) == "Mon 09:10"                        # :10/:30/:50 labels
    assert hm(r.bucket_start(et(2026, 9, 14, 16, 12), 20)) == "Mon 16:10"
    assert hm(r.bucket_end(r.bucket_start(et(2026, 9, 14, 16, 12), 20), 20)) == "Mon 16:15"   # the 5-minute stub bar
    assert hm(r.bucket_end(r.bucket_start(et(2026, 9, 14, 15, 35), 20), 20)) == "Mon 15:50"
    assert hm(r.bucket_start(et(2026, 9, 14, 14, 0), 240)) == "Mon 13:30"            # 4h RTH bars: 09:30 and 13:30 only
    assert hm(r.bucket_end(r.bucket_start(et(2026, 9, 14, 14, 0), 240), 240)) == "Mon 16:15"
    assert hm(r.bucket_start(et(2026, 9, 14, 15, 45), 60)) == "Mon 15:30" and hm(r.bucket_end(et(2026, 9, 14, 15, 30), 60)) == "Mon 16:15"
    assert r.session_id(et(2026, 9, 14, 9, 30)) == "2026-09-14"                       # VWAP resets on the first RTH bar
    assert r.time_close(et(2026, 9, 14, 16, 10), 20) == et(2026, 9, 14, 16, 15)
    assert r.next_open(et(2026, 9, 14, 16, 20)) == et(2026, 9, 15, 9, 30)
    assert "outside RTH" in r.describe(et(2026, 9, 14, 16, 20)) and r.describe(et(2026, 9, 14, 10, 10)).startswith("open (RTH)")
    # daily / weekly candles are unchanged by the chart session
    assert r.bucket_start(MON_0910_ET, 1440) == et(2026, 9, 13, 18, 0) and r.bucket_start(MON_0910_ET, 10080) == et(2026, 9, 13, 18, 0)
    assert r.bucket_end(et(2026, 9, 13, 18, 0), 1440) == et(2026, 9, 14, 17, 0)


def test_eth_intraday_anchor_is_the_session_open():
    e = CMECalendar(session="eth")
    assert hm(e.bucket_start(MON_0910_ET, 20)) == "Mon 09:00"                        # :00/:20/:40
    assert hm(e.bucket_start(et(2026, 9, 14, 3, 0), 240)) == "Mon 02:00"             # 18/22/02/06/10/14 ET
    assert hm(e.bucket_start(et(2026, 9, 14, 15, 0), 240)) == "Mon 14:00"
    assert hm(e.bucket_end(e.bucket_start(et(2026, 9, 14, 15, 0), 240), 240)) == "Mon 17:00"   # truncated at the close, next bar 18:00
    assert hm(e.bucket_start(et(2026, 9, 14, 18, 5), 240)) == "Mon 18:00"
    assert e.session_id(et(2026, 9, 14, 18, 5)) == "2026-09-15"
    k = CryptoCalendar()
    assert k.bucket_start(1789391400, 20) == 1789391400 - 1789391400 % 1200


def test_cme_holidays_2026():
    eq = CMECalendar(session="rth", group="equity")
    me = CMECalendar(session="rth", group="metals")
    assert not eq.is_open(et(2026, 12, 25, 10, 0)) and not eq.is_trade_date(date(2026, 12, 25))
    assert eq.next_open(et(2026, 12, 25, 10, 0)) == et(2026, 12, 28, 9, 30)
    assert eq.is_open(et(2026, 11, 26, 12, 59)) and not eq.is_open(et(2026, 11, 26, 13, 0))     # Thanksgiving halt 13:00 ET
    assert me.is_open(et(2026, 11, 26, 14, 0)) and not me.is_open(et(2026, 11, 26, 14, 30))     # metals 14:30
    assert eq.is_open(et(2026, 11, 26, 18, 0))                                                     # reopens for Friday's session
    assert eq.session_id(et(2026, 11, 26, 10, 0)) == "2026-11-27" == eq.session_id(et(2026, 11, 27, 10, 0))   # merged daily bar
    assert eq.bucket_start(et(2026, 11, 27, 10, 0), 1440) == et(2026, 11, 25, 18, 0)
    assert hm(eq.bucket_end(eq.bucket_start(et(2026, 11, 26, 12, 50), 20), 20)) == "Thu 13:00"   # last RTH bar truncated at the halt
    assert not eq.intraday_open(et(2026, 11, 26, 13, 5))
    assert eq.session_id(et(2026, 12, 24, 10, 0)) == "2026-12-24"                                 # Christmas Eve: no reopen -> own bar
    assert "early close" in eq.describe(et(2026, 11, 27, 10, 0))
    assert not eq.is_open(et(2027, 1, 1, 10, 0)) and eq.next_open(et(2027, 1, 1, 10, 0)) == et(2027, 1, 4, 9, 30)


def test_aggregator_bucket_end_and_feed_clock_flush():
    r = CMECalendar(session="rth")
    agg = Aggregator(20, r.bucket_start, r.bucket_end)
    t0 = et(2026, 9, 14, 16, 10)
    out = []
    for k in range(5):                                   # 16:10..16:14 -> the stub closes on its 5th minute
        out += agg.push(B(t0 + 60 * k, 1, 2, 0.5, 1.5))
    assert len(out) == 1 and out[0].ts == t0 and agg.forming is None
    # feed clock: a bucket is not closed while the feed's clock has not passed its end + grace
    agg2 = Aggregator(20, r.bucket_start, r.bucket_end)
    t1 = et(2026, 9, 14, 10, 10)
    for k in range(10):
        agg2.push(B(t1 + 60 * k, 1, 2, 0.5, 1.5))
    assert agg2.flush_if_stale(t1 + 600 + 48) is None                       # wall clock would say "ended"; the feed is 10 min behind
    assert agg2.flush_if_stale(t1 + 1200 + 48) is not None
    day = Aggregator(1440, r.bucket_start, r.bucket_end)
    so = et(2026, 9, 13, 18, 0)
    done = []
    for k in range(0, 23 * 60, 5):
        done += day.push(B(so + 60 * k, 1, 2, 0.5, 1.5), 5)
    assert len(done) == 1 and done[0].ts == so                                # closes at 17:00 (bucket_end), not 18:00


def test_heikin_ashi_and_slippage():
    ha = HeikinAshi()                                                      # exact arithmetic (no tick given)
    b1 = ha.transform(B(0, 100, 110, 90, 105))
    assert abs(b1.c - 101.25) < 1e-9 and abs(b1.o - 102.5) < 1e-9
    b2 = ha.transform(B(60, 105, 112, 104, 110))
    assert abs(b2.o - (102.5 + 101.25) / 2) < 1e-9 and b2.h == max(112, b2.o, b2.c)
    em = Emulator(100000, 0.0, 0.25, 20.0, slippage_ticks=2)
    em.process_bar(B(0, 100, 101, 99, 100), 0)
    em.entry("Long", 1, 1)
    em.exit("L1", "Long", qty=1, limit=110, stop=95, comment_profit="TP", comment_loss="SL")
    em.process_bar(B(60, 100, 100.5, 99.5, 100), 1)
    assert em.open[0].entry_price == 100.5                                  # 2 ticks x 0.25 worse for a buy
    em.process_bar(B(120, 100, 100.2, 94, 96), 2)
    assert em.closed[-1].exit_price == 94.5 and em.closed[-1].exit_comment == "SL"   # stop fills slip against the seller
    assert abs(em.closed[-1].profit - ((94.5 - 100.5) * 20)) < 1e-9


# ── feeds ──
def test_yahoo_parser_drops_nulls_quote_rows_and_placeholders():
    res = {"timestamp": [60, 120, 180, 240, 287], "indicators": {"quote": [{
        "open": [1, None, 3, 5, 5.5], "high": [2, 2, 4, 5, 5.5], "low": [0.5, 1, 2.5, 5, 5.5], "close": [1.5, None, 3.5, 5, 5.5], "volume": [10, None, 30, 0, 0]}]}}
    bars = Yahoo._bars(res, 60)
    assert [b.ts for b in bars] == [60, 180] and bars[1].v == 30      # null minute, flat zero-volume placeholder (240) and the quote row (287) are gone
    daily = Yahoo._bars({"timestamp": [1789344000], "indicators": {"quote": [{"open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [0]}]}}, 86400)
    assert len(daily) == 1                                             # daily rows are never alignment-filtered


def test_contract_roll_rule():
    assert third_friday(2026, 9) == date(2026, 9, 18)
    assert contract_months("HMUZ", date(2026, 9, 14), 2) == [(2026, 9), (2026, 12)]
    assert contract_months("HMUZ", date(2026, 9, 19), 1) == [(2026, 12)]              # the day after expiry
    assert ticker_for("NQ", 2026, 12) == "NQZ26.CME" and ticker_for("YM", 2027, 3) == "YMH27.CBT"
    r = ContractRoll("NQ", date(2026, 9, 14))
    assert r.ticker == "NQU26.CME" and r.next_ticker == "NQZ26.CME"
    assert not r.decide(568263, 21238) and r.decide(51768, 60000) and not r.decide(None, 5)
    prev = r.roll()
    assert prev == "NQU26.CME" and r.ticker == "NQZ26.CME" and r.next_ticker == "NQH27.CME"
    so = et(2026, 9, 13, 18, 0)                                                        # Monday's session opened Sunday 18:00
    rows = [(et(2026, 9, 10, 0, 0), 1, 500.0), (et(2026, 9, 11, 0, 0), 1, 600.0), (et(2026, 9, 14, 0, 0), 1, 50.0)]
    assert last_completed_volume(rows, so) == 600.0                                    # Friday's, not the running session's row


# ── assets / inputs ──
def test_assets_registry_and_spec_tokens():
    nq = resolve("NQ1!")
    assert nq.symbol == "NQ" and nq.multiplier == 20.0 and nq.mintick == 0.25 and nq.calendar == "cme" and nq.session == "rth" and nq.roll == "volume"
    gc = parse_spec("GC@10:NQ-10m-original", "20")
    assert gc.symbol == "GC" and gc.chart_tf == "10" and gc.preset == "NQ-10m-original" and gc.group == "metals" and gc.roll == "none"
    btc = parse_spec("BTCUSD")
    assert btc.feed == "coinbase" and btc.calendar == "crypto"
    assert tf_minutes("1W") == 10080 and tf_minutes("4H") == 240
    for bad in ('a">x', "..\\..\\evil", "NQ/../x"):
        with pytest.raises(ValueError):
            resolve(bad)


def test_input_value_validation_and_preset_confinement(tmp_path):
    validate_values({"tp1_pts": 100, "use_kalman": False, "htf_tf_1": "60", "sess_window": "0800-1600", "tide_confirm_mode": "Strict"})
    for bad in ({"tp1_pts": "100"}, {"tp1_pts": float("nan")}, {"tp1_pts": float("inf")}, {"use_kalman": "yes"}, {"qty_contracts": 2.5},
                {"htf_tf_1": "abc"}, {"sess_window": 12345}, {"tide_confirm_mode": "Weird"}, {"qty_contracts": 0}):
        with pytest.raises(ValueError):
            validate_values(dict(bad))
    d = {"qty_contracts": 3.0}
    validate_values(d)
    assert d["qty_contracts"] == 3 and isinstance(d["qty_contracts"], int)
    (tmp_path / "presets").mkdir()
    assert preset_path(str(tmp_path), "NQ-20m ultracoded").endswith("NQ-20m ultracoded.json")
    for bad in ("../outside", "..\\outside", "", "a/b", "x" * 80):
        with pytest.raises(ValueError):
            preset_path(str(tmp_path), bad)
    (tmp_path / "presets" / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_inputs(parse_spec("NQ"), str(tmp_path), "nq", "bad")
    (tmp_path / "presets" / "nan.json").write_text('{"tp1_pts": NaN}', encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_inputs(parse_spec("NQ"), str(tmp_path), "nq", "nan")


def test_tv_values_and_preset_resolution(tmp_path):
    assert tv_value("x", "On", "bool") is True and tv_value("x", "08:00 – 16:00", "session") == "0800-1600"
    assert tv_value("x", "1 week", "timeframe") == "W" and tv_value("x", "20 minutes", "timeframe") == "20" and tv_value("x", "1D", "timeframe") == "D"
    labels = {e["name"]: e["label"] for e in load_meta()}
    props = {labels["tp1_pts"]: "100", labels["use_kalman"]: "Off", labels["htf_tf_5"]: "1 week", labels["sess_window"]: "08:00 – 16:00", "Chart type": "Heikin Ashi"}
    ov = inputs_from_tv_properties(props)
    assert ov == {"tp1_pts": 100.0, "use_kalman": False, "htf_tf_5": "W", "sess_window": "0800-1600"}
    base = tmp_path
    (base / "presets").mkdir()
    (base / "presets" / "P.json").write_text(json.dumps({"_meta": {"chart_type": "heikin_ashi", "slippage_ticks": 2}, "tp1_pts": 100, "qty_contracts": 10}), encoding="utf-8")
    (base / "inputs.NQ.json").write_text(json.dumps({"qty_contracts": 3}), encoding="utf-8")
    spec = parse_spec("NQ")
    inp, meta, sources = resolve_inputs(spec, str(base), "nq", "P")
    assert inp.tp1_pts == 100 and inp.qty_contracts == 3 and meta["slippage_ticks"] == 2 and sources[1].startswith("preset:P")
    inp2, _, _ = resolve_inputs(spec, str(base), "nq", "P", {"qty_contracts": 7})
    assert inp2.qty_contracts == 7
    with pytest.raises(ValueError):
        resolve_inputs(spec, str(base), "nq", None, {"nope": 1})


def test_shipped_presets_load(tmp_path):
    import shutil
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "presets")
    shutil.copytree(src, str(tmp_path / "presets"))                        # isolated from any inputs.<SYM>.json in the working tree
    here = str(tmp_path)
    for name in ("NQ-20m-ultracoded", "NQ-10m-original"):
        inp, meta, _ = resolve_inputs(parse_spec("NQ"), here, "nq", name)
        assert meta["chart_type"] == "heikin_ashi"
    a, ma, _ = resolve_inputs(parse_spec("NQ"), here, "nq", "NQ-20m-ultracoded")
    assert a.tp1_pts == 100 and a.sl_pts == 80 and a.qty_contracts == 10 and a.htf_tf_5 == "W" and a.use_kalman is False and a.tide_confirm_mode == "Strict" and ma["slippage_ticks"] == 2
    b, _, _ = resolve_inputs(parse_spec("NQ"), here, "nq", "NQ-10m-original")
    assert b.tpsl_mode == "Structure-Based" and b.qty_contracts == 8 and b.sess_window == "0530-1600" and b.use_trailing_tp2


# ── request.security semantics ──
def test_tfchain_heikin_ashi_and_ltf_intrabar():
    t0 = 1_700_000_000 - 1_700_000_000 % 3600
    real, ha = TFChain(60), TFChain(60, ha=True)
    px = 100.0
    for k in range(60 * 30):                                   # 30 hourly bars from 1m bars, a sawtooth: HA smooths it
        px += 0.3 if (k // 60) % 3 else -0.5
        for ch in (real, ha):
            ch.push_sub_bar(B(t0 + 60 * k, px, px + .4, px - .4, px), 1)
    assert real.bars == ha.bars == 30
    assert ha.last_bar is not None and abs(ha.last_bar.o - real.last_bar.o) > 1e-9       # the HA chain evaluated HA bars
    first, last = TFChain(2, ltf_intrabar="first"), TFChain(2, ltf_intrabar="last")
    for k in range(60):
        v = 1.0 + (k // 10)                                   # step up every 10 minutes
        for ch in (first, last):
            ch.push_sub_bar(B(t0 + 60 * k, v, v + (0.5 if k >= 26 else 0.0), v, v), 1)
    a = first.ltf_values(t0 + 300 * 5, 5)                     # chart bar 25:00-30:00
    b = last.ltf_values(t0 + 300 * 5, 5)
    assert first._value_before_bucket(t0 + 60 * 24) == a       # [1] of the first intrabar (24:00) ...
    assert last._value_before_bucket(t0 + 60 * 28) == b        # ... vs [1] of the last intrabar (28:00)


def test_pe_na_poisoning_reproduced_by_default():
    def run(fix: bool):
        inp = crypto_profile(100.0, 0.01)
        from dataclasses import replace
        inp = replace(inp, use_pe=True, use_pe_weighted=True, pe_na_poison_fix=fix)
        em = Emulator(500000, 2.0, 0.01, 1000.0)
        st = PulseStrategy(inp, em, mintick=0.01, tf_minutes=5)
        vals = []
        px = 100.0
        import random
        rnd = random.Random(7)
        for k in range(200):
            px += rnd.uniform(-1, 1)
            s = st.on_bar(B(k * 300, px, px + 0.5, px - 0.5, px + rnd.uniform(-0.3, 0.3)), k, [(-1.0, 0.6)] * 5, [(-1.0, 10.0, 0.6)] * 2)
            vals.append(s["pe_norm"])
        return vals
    tv = run(False)
    assert all(v == 0.0 for v in tv[40:]), "TradingView: pe_norm stuck at 0 (na-poisoned weights)"
    fixed = run(True)
    assert any(0.0 < v <= 1.0 for v in fixed[40:]) and max(fixed[40:]) > 0.3


# ── journal ──
def test_journal_ignores_duplicate_replays(tmp_path):
    from icarus_engine.emulator import Fill
    path = str(tmp_path / "j.db")
    j = Journal(path)
    f = Fill(ts=1, bar=1, entry_id="Long", side="buy", qty=1, price=10.0, kind="entry", comment="Long", profit=None, position_after=1)
    j.add_fill("NQ", f, live=False); j.add_fill("NQ", f, live=False)
    assert j.con.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1
    j.con.close()
    con = sqlite3.connect(path)                                     # an old journal full of duplicates is cleaned on open
    con.execute("DROP INDEX fills_uq2")
    con.execute("INSERT INTO fills (symbol,ts,entry_id,side,qty,price,kind,comment,profit,position_after,live,run_id) VALUES ('NQ',1,'Long','buy',1,10.0,'entry','Long',NULL,1,0,?)", (j.run_id,))
    con.commit(); con.close()
    j2 = Journal(path)
    assert j2.con.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1


def test_emulator_bracket_after_limit_fill_inside_leg():
    em = Emulator(100000, 0.0, 0.01, 1.0)
    em.process_bar(B(0, 100, 100.5, 99.5, 100), 0)
    em.entry("Long", 1, 1, limit=98.0)
    em.exit("L1", "Long", qty=1, limit=99.0, stop=90.0, comment_profit="TP", comment_loss="SL")
    em.process_bar(B(60, 100, 104, 97, 100), 1)              # O->H->L->C (open nearer the low): limit fills at 98 in the H->L leg, TP at 99 in the L->C leg - not at the open
    assert em.closed and em.closed[-1].entry_price == 98.0 and em.closed[-1].exit_price == 99.0 and em.closed[-1].exit_comment == "TP"


def test_server_auth_host_and_body_limits(tmp_path):
    import threading
    import urllib.request
    import urllib.error
    from icarus_engine.runtime import Portfolio
    from icarus_engine.server import serve
    (tmp_path / "presets").mkdir()
    port = Portfolio(Journal(":memory:"), str(tmp_path))
    srv = serve(port, 0, token="t0k", start=False)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, method="GET", headers=None, data=None):
        req = urllib.request.Request(base + path, method=method, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as ex:
            return ex.code
    assert call("/healthz") == 200
    assert call("/healthz", headers={"Host": "evil.test"}) == 403                          # DNS rebinding
    body = b'{"asset": "*"}'
    for h in ({}, {"Authorization": "Bearert0k"}, {"Authorization": "Bearer  t0k "}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic t0k"}):
        assert call("/admin/pause", "POST", dict(h, **{"Content-Type": "application/json"}), body) == 401, h
    ok = {"Authorization": "Bearer t0k", "Content-Type": "application/json"}
    assert call("/admin/pause", "POST", ok, body) == 200
    assert call("/admin/pause", "POST", dict(ok, **{"Content-Length": "2000000"}), b"") in (413, 400)
    assert call("/admin/pause", "POST", ok, b'{"asset": NaN}') == 400
    assert call("/admin/pause", "POST", ok, b'[1,2]') == 400
    assert call("/admin/preset", "POST", ok, b'{"preset": "../../inputs"}') == 400
    srv.shutdown()


def test_portfolio_preset_switch_uses_the_asset_preset(tmp_path):
    from icarus_engine.runtime import Portfolio
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "A.json").write_text(json.dumps({"tp1_pts": 100}), encoding="utf-8")
    (tmp_path / "presets" / "B.json").write_text(json.dumps({"tp1_pts": 200, "_meta": {"slippage_ticks": 3}}), encoding="utf-8")
    port = Portfolio(Journal(":memory:"), str(tmp_path), preset="A")
    spec = parse_spec("BTC")                                        # crypto: no network needed for the calendar; feed calls are avoided below
    port.feeds["coinbase"].mintick = lambda s: 0.01
    r = port.add_asset(spec, start=False)
    assert port.preset_for(r) == "A" and r.inputs_base.tp1_pts == 100
    r.warm = True                                               # isolated fixture is ready; no background warmup is running
    r.spec.preset = "B"; r.cfg.preset = "B"                        # what /admin/preset does
    port.rewarm_asset("BTC")
    assert port.preset_for(r) == "B" and r.inputs_base.tp1_pts == 200 and r.spec.slippage_ticks == 3


def test_emulator_tracks_runup_drawdown_and_bars_per_trade():
    em = Emulator(100000, 2.0, 0.25, 20.0)
    em.process_bar(B(0, 100, 101, 99, 100), 0)
    em.entry("Long", 1, 2)                                            # fills at bar 1 open = 100
    em.exit("L1", "Long", qty=2, limit=104, stop=90, comment_profit="TP", comment_loss="SL")
    em.process_bar(B(60, 100, 103, 99, 102), 1)                       # best +3, worst -1
    em.process_bar(B(120, 102, 102.5, 98, 101), 2)                    # worst -2
    em.process_bar(B(180, 101, 105, 100.5, 104), 3)                   # TP at 104 on the way to 105 (O->H->L->C, open nearer the high)
    t = em.closed[-1]
    assert t.exit_comment == "TP" and t.exit_price == 104
    # TradingView: excursion up to the exit fill on the exit bar, less the entry commission (export: pnl 3,996 / run-up 3,998 / commission 4)
    assert t.runup == pytest.approx(4.0 * 20 * 2 - 2.0 * 2)
    assert t.drawdown == pytest.approx(-2.0 * 20 * 2 - 2.0 * 2)
    assert t.bars == 2                                                 # Duration (bars): exit bar 3 - entry bar 1
    assert em.closed[-1].profit == pytest.approx(4.0 * 20 * 2 - 2.0 * 2 * 2)


def _synthetic_runner(tmp_path, n_days=3):
    """An RTH NQ runner warmed from synthetic 1-minute bars - no network."""
    from icarus_engine.runtime import AssetRunner, Portfolio, RunnerConfig
    from icarus_engine.strategy.inputs import Inputs
    import random
    (tmp_path / "presets").mkdir(exist_ok=True)
    port = Portfolio(Journal(":memory:"), str(tmp_path), preset=None, warmup_bars=200)
    spec = parse_spec("NQ")
    cfg = RunnerConfig(spec=spec, inputs=Inputs(), warmup_bars=200, sources=[], profile="nq", preset=None, pts_ref_price=0.0)
    r = AssetRunner(cfg, port.journal, port.feeds)
    rnd = random.Random(11)
    px = 20000.0
    for d in range(n_days):
        day = date(2026, 9, 7) + timedelta(days=d)                      # Mon..Wed
        t0 = et(day.year, day.month, day.day, 9, 30)
        for k in range(405):                                          # 09:30 .. 16:14 ET
            px += rnd.uniform(-8, 8)
            r.on_sub_bar(B(t0 + 60 * k, px, px + 3, px - 3, px + rnd.uniform(-2, 2), 50 + k % 7), 1, live=False)
    r.warm = True
    port.runners["NQ"] = r; port.order.append("NQ")
    return port, r


def test_backtest_job_runs_on_cached_bars_and_reports_tradingview_shape(tmp_path):
    from icarus_engine.backtest import run_backtest
    port, r = _synthetic_runner(tmp_path)
    before = r.bar_index
    res = run_backtest(port, "NQ", fill_on="real", inputs={"qty_contracts": 1})
    assert r.bar_index == before and r.em is not None                          # the live runner is untouched
    assert res["bars"] == before + 1 and res["asset"] == "NQ" and res["config"]["fill_on"] == "real"
    s = res["summary"]
    for key in ("net_profit", "total_trades", "percent_profitable", "profit_factor", "max_drawdown", "sharpe", "buy_and_hold_pnl", "cagr_pct"):
        assert key in s and set(s[key]) == {"all", "long", "short"}
    assert len(res["equity"]) == res["bars"] and res["equity"][0][1] == res["config"]["capital"]
    assert {"performance", "trades", "risk"} <= set(res["rows"])
    for t in res["trades"]:
        assert t["entry_ts"] < t["exit_ts"] or t["exit_ts"] is None
        assert "runup" in t and "drawdown" in t and "bars" in t and "cum_pnl" in t
    csv_text = res["csv"]
    assert csv_text.splitlines()[0].startswith("Trade number,Type,Date and time,Signal,Price USD,Size (qty)")


def test_backtest_routes_end_to_end(tmp_path):
    import threading, urllib.request, urllib.error
    from icarus_engine.server import serve
    from icarus_engine.backtest import trades_csv
    port, r = _synthetic_runner(tmp_path, n_days=8)                          # enough bars for a couple of trades
    srv = serve(port, 0, token="t0k", start=False)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    hdr = {"Authorization": "Bearer t0k", "Content-Type": "application/json"}

    def call(path, method="GET", data=None, headers=None):
        req = urllib.request.Request(base + path, method=method, data=(json.dumps(data).encode() if data is not None else None), headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as ex:
            return ex.code, ex.read()
    st, body = call("/admin/backtest", "POST", {"asset": "NQ", "fill_on": "chart", "inputs": {"qty_contracts": 1}}, hdr)
    assert st == 200, body
    job = json.loads(body)["job"]
    for _ in range(100):
        st, body = call(f"/api/backtest/{job}")
        d = json.loads(body)
        if d["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert d["status"] == "done", d.get("error")
    res = d["result"]
    assert res["config"]["fill_on"] == "chart" and res["bars"] == r.bar_index + 1 and "csv" not in res
    st, body = call(f"/api/backtest/{job}/trades.csv")
    assert st == 200 and body.decode().startswith("Trade number,")
    # compare the job with a TradingView export made from its own trades -> everything must match
    csv_text = trades_csv(res["trades"])
    st, body = call("/admin/backtest/compare", "POST", {"job": job, "csv": csv_text}, hdr)
    assert st == 200, body
    rep = json.loads(body)["report"]["summary"]
    assert len(res["trades"]) >= 2, "synthetic data must produce trades for the comparison to be meaningful"
    assert rep["engine_trades"] == rep["tv_trades"] >= 1 and rep["engine_only"] == 0 and rep["tv_only"] == 0 and rep["exit_signature_agreement_pct"] == 100.0
    st, body = call("/admin/backtest", "POST", {"asset": "NQ", "inputs": {"nope": 1}}, hdr)
    assert st == 400
    st, body = call("/admin/backtest", "POST", {"asset": "NQ", "preset": "../x"}, hdr)
    assert st == 400
    srv.shutdown()


class _FakeYahoo:
    """Records which symbols were asked for; returns a few aligned bars."""
    def __init__(self, price=29000.0):
        self.calls = []; self.price = price; self._meta = {}
    def candles(self, symbol, granularity, start_ts, end_ts):
        self.calls.append((symbol, granularity))
        self._meta[symbol] = {"regularMarketTime": int(end_ts) + 600, "regularMarketPrice": self.price}
        t0 = et(2026, 9, 10, 9, 30)
        return [B(t0 + granularity * k, self.price, self.price + 1, self.price - 1, self.price, 10) for k in range(3)]
    def daily_volume(self, symbol, days=5):
        self.calls.append((symbol, "daily"))
        return [(et(2026, 9, 10, 0, 0), self.price - 100, 500000.0), (et(2026, 9, 11, 0, 0), self.price, 600000.0), (et(2026, 9, 14, 0, 0), self.price + 300, 50000.0)]
    def ticker(self, symbol):
        self.calls.append((symbol, "ticker")); return self.price + 300
    def mintick(self, symbol):
        return 0.25


def test_warmup_uses_the_contract_ticker_for_intraday_history(tmp_path):
    """Yahoo's NQ=F splices the next contract in unadjusted on its roll day; intraday warm-up must come from the contract."""
    from icarus_engine.runtime import AssetRunner, Journal, RunnerConfig
    from icarus_engine.strategy.inputs import Inputs
    (tmp_path / "presets").mkdir()
    fy = _FakeYahoo()
    r = AssetRunner(RunnerConfig(spec=parse_spec("NQ"), inputs=Inputs(), warmup_bars=100, sources=[], profile="nq", preset=None, pts_ref_price=0.0),
                    Journal(":memory:"), {"yahoo": fy})
    assert r.live_ticker.startswith("NQ") and r.live_ticker.endswith(".CME")
    r._warmup_yahoo(et(2026, 9, 1, 18, 0), et(2026, 9, 14, 16, 0))
    intraday = {sym for sym, g in fy.calls if g in (60, 300, 900)}
    daily = {sym for sym, g in fy.calls if g == 86400}
    assert intraday == {r.live_ticker}, intraday                      # never NQ=F for 1m/5m/15m
    assert daily == {"NQ=F"}                                          # years of daily history stay on the continuous symbol


def test_point_scaling_reference_is_the_last_completed_daily_close(tmp_path):
    from icarus_engine.runtime import Portfolio
    (tmp_path / "presets").mkdir()
    port = Portfolio(Journal(":memory:"), str(tmp_path))
    fy = _FakeYahoo(); port.feeds["yahoo"] = fy
    ref = port._ref_price(now=et(2026, 9, 14, 10, 0))                     # during Monday's session: Friday's close
    assert ref == 29000.0 and ("ticker" not in {g for _, g in fy.calls})   # the last COMPLETED session's close, not the live (possibly rolled) quote
    assert port._ref_price(now=et(2026, 9, 14, 10, 0)) == 29000.0 and len([c for c in fy.calls if c[1] == "daily"]) == 1   # cached


def test_journal_keeps_two_identical_same_bar_pieces_and_stamps_run_id(tmp_path):
    """Two SL pieces of a 2-contract position close at the same price/bar/comment - both must be journaled (audit D1/D2)."""
    from icarus_engine.emulator import ClosedTrade, Fill
    j = Journal(str(tmp_path / "j.db"))
    a = ClosedTrade("Short", -1, 1, 29032.25, 10, 1789394400, 29152.75, 15, 1789400400, "S_SL", -2414.0, "Short", "sl")
    b = ClosedTrade("Short", -1, 1, 29032.25, 10, 1789394400, 29152.75, 15, 1789400400, "S_SL", -2414.0, "Short", "sl")
    j.add_trade("NQ", a, live=True, piece=0); j.add_trade("NQ", b, live=True, piece=1)
    j.add_trade("NQ", b, live=True, piece=1)                                        # a replay of the same piece is still ignored
    assert j.con.execute("SELECT COUNT(*), SUM(profit) FROM trades").fetchone() == (2, -4828.0)
    f1 = Fill(ts=1789400400, bar=15, entry_id="Short", side="buy", qty=1, price=29152.75, kind="sl", comment="S_SL", profit=-2414.0, position_after=-1)
    f2 = Fill(ts=1789400400, bar=15, entry_id="Short", side="buy", qty=1, price=29152.75, kind="sl", comment="S_SL", profit=-2414.0, position_after=0)
    j.add_fill("NQ", f1, True); j.add_fill("NQ", f2, True); j.add_fill("NQ", f2, True)
    assert j.con.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 2
    assert j.con.execute("SELECT COUNT(DISTINCT run_id) FROM trades").fetchone()[0] == 1 and j.run_id > 0


def test_summary_feed_delay_only_while_open_and_expiry_fallback_flattens(tmp_path, monkeypatch):
    from icarus_engine.runtime import AssetRunner, Journal, RunnerConfig
    from icarus_engine.strategy.inputs import Inputs
    from datetime import date as _date
    # Construct the runner before the tested expiry; wall-clock date must not
    # silently initialize it on a later contract when this regression runs.
    monkeypatch.setattr("icarus_engine.runtime.time.time", lambda: et(2026, 9, 14, 10, 0))
    (tmp_path / "presets").mkdir()
    fy = _FakeYahoo()
    r = AssetRunner(RunnerConfig(spec=parse_spec("NQ"), inputs=Inputs(), warmup_bars=100, sources=[], profile="nq", preset=None, pts_ref_price=0.0),
                    Journal(":memory:"), {"yahoo": fy})
    r.feed_delay = 1726.0
    closed_ts = et(2026, 9, 14, 17, 30)                                           # Globex break: no feed clock to report
    assert r._feed_delay_at(closed_ts) == 0.0 and r._feed_delay_at(et(2026, 9, 14, 12, 0)) == 1726.0
    # expiry passed without a volume roll: move to the next contract AND flatten
    r.em.process_bar(B(et(2026, 9, 18, 9, 30), 29000, 29010, 28990, 29000), 0)
    r.em.entry("Long", 1, 2); r.em.process_bar(B(et(2026, 9, 18, 9, 50), 29000, 29010, 28990, 29000), 1)
    r.last_price = 29000.0
    assert r.em.position_size == 2
    r._check_roll(et(2026, 9, 21, 10, 0), today=_date(2026, 9, 21))
    assert r.live_ticker == "NQZ26.CME" and r.em.position_size == 0


def test_cme_crypto_calendar_is_24_7_since_may_2026():
    """CME Bitcoin futures trade around the clock since 2026-05-29 (CME press release) with a weekend maintenance window."""
    from icarus_engine.calendar import get_calendar
    c = get_calendar("cme_crypto")
    assert c.is_open(et(2026, 9, 13, 12, 0)) and c.is_open(et(2026, 9, 12, 12, 0))          # Sunday noon, Saturday noon
    assert c.is_open(et(2026, 9, 14, 17, 30))                                              # no daily maintenance break
    assert not c.is_open(et(2026, 9, 12, 3, 30)) and c.is_open(et(2026, 9, 12, 5, 30))     # Saturday 02:00-04:00 CT maintenance
    assert c.is_open(et(2026, 11, 26, 14, 0)) and c.is_open(et(2026, 12, 25, 12, 0))       # no holiday halts
    assert c.session_id(et(2026, 9, 14, 18, 5)) == "2026-09-15" and c.bucket_start(et(2026, 9, 14, 3, 0), 240) == et(2026, 9, 14, 2, 0)
    assert c.intraday_open(et(2026, 9, 13, 12, 0)) and c.describe(et(2026, 9, 13, 12, 0)).startswith("open")
    spec = parse_spec("BTCF")
    assert spec.calendar == "cme_crypto" and spec.session == "eth" and spec.roll == "none"


def test_background_launcher_only_accepts_a_live_health_endpoint():
    """A stale cmd.exe wrapper must not block a replacement dashboard process."""
    from pathlib import Path
    launcher = Path(__file__).parents[1] / "start-engine-background.ps1"
    script = launcher.read_text(encoding="utf-8")
    assert "Invoke-WebRequest" in script
    assert "/healthz" in script
    assert "Remove-Item $pidFile" in script


def test_emulator_every_order_gapped_through_at_the_open_fills_at_the_open():
    """Lane B D1: a bar that opens beyond BOTH bracket pieces' levels must fill both at the open (TradingView gap rule per order)."""
    em = Emulator(100000, 0.0, 0.25, 20.0)
    em.process_bar(B(0, 100, 101, 99, 100), 0)
    em.entry("Long", 1, 2)
    em.process_bar(B(60, 100, 100.5, 99.5, 100), 1)
    em.exit("L1", "Long", qty=1, limit=110, stop=90, comment_profit="TP1", comment_loss="SL")
    em.exit("L2", "Long", qty=1, limit=110.25, stop=90, comment_profit="TP2", comment_loss="SL")
    em.process_bar(B(120, 85, 86, 84, 85), 2)                        # gaps through the shared stop
    assert [(t.exit_comment, t.exit_price) for t in em.closed[-2:]] == [("SL", 85.0), ("SL", 85.0)] and em.position_size == 0
    em2 = Emulator(100000, 0.0, 0.25, 20.0)
    em2.process_bar(B(0, 100, 101, 99, 100), 0)
    em2.entry("Short", -1, 2)
    em2.process_bar(B(60, 100, 100.5, 99.5, 100), 1)
    em2.exit("S1", "Short", qty=1, limit=90, stop=110, comment_profit="TP1", comment_loss="SL")
    em2.exit("S2", "Short", qty=1, limit=89.75, stop=110, comment_profit="TP2", comment_loss="SL")
    em2.process_bar(B(120, 88, 89, 87, 88), 2)                       # gaps through both TPs
    assert [(t.exit_comment, t.exit_price) for t in em2.closed[-2:]] == [("TP1", 88.0), ("TP2", 88.0)] and em2.position_size == 0


def test_emulator_exits_close_fifo_like_tradingview():
    """Lane B D2: TradingView closes the OLDEST open trade first even when the exit names another entry id."""
    em = Emulator(1000000, 0.0, 0.25, 20.0)
    em.process_bar(B(0, 100, 101, 99, 100), 0)
    em.entry("TideLong", 1, 5)
    em.process_bar(B(60, 100, 100.5, 99.5, 100), 1)
    em.entry("Long", 1, 2)
    em.process_bar(B(120, 100, 100.5, 99.5, 100), 2)
    em.exit("L1", "Long", qty=1, limit=105, stop=90, comment_profit="TP1", comment_loss="SL")
    em.process_bar(B(180, 100, 106, 99.5, 105), 3)
    t = em.closed[-1]
    assert t.entry_id == "TideLong" and t.qty == 1 and t.exit_comment == "TP1" and em.position_size == 6
    assert em.qty_open("TideLong") == 4 and em.qty_open("Long") == 2


def test_emulator_runup_never_negative():
    em = Emulator(100000, 2.0, 0.25, 20.0)
    em.process_bar(B(0, 100, 101, 99, 100), 0)
    em.entry("Long", 1, 1)
    em.exit("L1", "Long", qty=1, limit=110, stop=95, comment_profit="TP", comment_loss="SL")
    em.process_bar(B(60, 100, 100, 94, 95), 1)                        # straight down from the open: no favourable excursion
    assert em.closed[-1].exit_comment == "SL" and em.closed[-1].runup == 0.0 and em.closed[-1].drawdown < 0


def test_heikin_ashi_values_are_tick_rounded_like_tradingview():
    ha = HeikinAshi(mintick=0.25)
    b1 = ha.transform(B(0, 100.00, 110.25, 90.00, 105.25))                  # real prices are tick multiples; HA averages are not
    assert b1.o % 0.25 == 0 and b1.c % 0.25 == 0 and b1.h % 0.25 == 0 and b1.l % 0.25 == 0
    assert b1.c == 101.5                                                    # (100 + 110.25 + 90 + 105.25) / 4 = 101.375 -> 101.5
    b2 = ha.transform(B(60, 105.25, 112.00, 104.00, 111.00))
    assert b2.o == round((b1.o + b1.c) / 2 / 0.25) * 0.25 and b2.o % 0.25 == 0
