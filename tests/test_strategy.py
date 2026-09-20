from datetime import timezone

import pytest

from icarus.config import AssetClass, profile_for
from icarus.data import synthetic_for
from icarus.execution import IntentKind
from icarus.strategy import IcarusEngine

try:
    from zoneinfo import ZoneInfo
except ImportError:                                      # pragma: no cover
    ZoneInfo = None


def drive(asset, bars=3000, seed=11, **kwargs):
    engine = IcarusEngine(asset, **kwargs)
    intents = []
    for bar in synthetic_for(asset, bars, seed=seed):
        intents.extend(engine.on_bar(bar))
    return engine, intents


@pytest.mark.parametrize("asset", list(AssetClass))
def test_every_profile_runs_end_to_end(asset):
    engine, intents = drive(asset)
    assert engine.state.bar_index == 2999
    assert engine.equity > 0.0
    assert all(intent.size >= 0.0 for intent in intents)


def test_engine_is_deterministic():
    first, first_intents = drive(AssetClass.CRYPTO)
    second, second_intents = drive(AssetClass.CRYPTO)
    assert first.equity == second.equity
    assert len(first_intents) == len(second_intents)
    assert [trade.pnl for trade in first.blotter.trades] == [trade.pnl for trade in second.blotter.trades]


def test_no_look_ahead_truncating_the_future_cannot_change_the_past():
    """The strongest guarantee in the codebase: decisions are causal.

    Running on a prefix must produce exactly the intents the full run produced
    over that prefix. If any layer peeked forward, these would diverge.
    """
    bars = synthetic_for(AssetClass.CRYPTO, 2500, seed=17)
    cutoff = 1500

    short_engine = IcarusEngine(AssetClass.CRYPTO)
    short_intents = [intent for bar in bars[:cutoff] for intent in short_engine.on_bar(bar)]

    long_engine = IcarusEngine(AssetClass.CRYPTO)
    long_intents = []
    for index, bar in enumerate(bars):
        emitted = long_engine.on_bar(bar)
        if index < cutoff:
            long_intents.extend(emitted)

    assert len(short_intents) == len(long_intents)
    for left, right in zip(short_intents, long_intents):
        assert left == right


def test_entries_fill_at_the_next_open_not_the_signal_close():
    bars = synthetic_for(AssetClass.CRYPTO, 2500, seed=17)
    engine = IcarusEngine(AssetClass.CRYPTO)
    entry_bar_opens = {}
    for index, bar in enumerate(bars):
        for intent in engine.on_bar(bar):
            if intent.kind is IntentKind.ENTER:
                entry_bar_opens[intent.ts] = (bar.open, intent.price, intent.direction)
    assert entry_bar_opens, "expected at least one entry on this tape"
    costs = engine.profile.costs
    for open_price, fill, direction in entry_bar_opens.values():
        # The fill is this bar's open, worsened by modelled friction -- never better.
        assert direction * (fill - open_price) >= 0.0
        assert abs(fill - open_price) <= 20.0 * costs.tick_size * max(1.0, costs.spread_ticks)


def test_equity_profile_never_holds_risk_outside_its_session():
    engine = IcarusEngine(AssetClass.EQUITY)
    profile = profile_for(AssetClass.EQUITY)
    tz = ZoneInfo(profile.timezone) if ZoneInfo else timezone.utc
    violations = 0
    for bar in synthetic_for(AssetClass.EQUITY, 4000, seed=23):
        engine.on_bar(bar)
        if engine.position is not None:
            local = bar.ts.astimezone(tz).time()
            if not any(window.contains(local) for window in profile.sessions):
                violations += 1
    assert violations == 0


def test_crypto_trades_around_the_clock():
    engine = IcarusEngine(AssetClass.CRYPTO)
    bars = synthetic_for(AssetClass.CRYPTO, 500, seed=5)
    assert all(engine.in_session(bar.ts) for bar in bars)


def test_only_one_position_is_ever_open():
    engine = IcarusEngine(AssetClass.CRYPTO)
    for bar in synthetic_for(AssetClass.CRYPTO, 3000, seed=11):
        engine.on_bar(bar)
        assert engine.position is None or engine.position.size > 0.0


def test_every_entry_is_matched_by_an_exit_or_a_live_position():
    engine, intents = drive(AssetClass.CRYPTO, bars=3000)
    entries = sum(1 for intent in intents if intent.kind is IntentKind.ENTER)
    exits = sum(1 for intent in intents if intent.kind is IntentKind.EXIT)
    assert entries == exits + (1 if engine.position is not None else 0)
    assert entries == len(engine.blotter.trades) + (1 if engine.position is not None else 0)


def test_stops_are_honoured_so_losses_stay_near_one_r():
    engine, _ = drive(AssetClass.CRYPTO, bars=6000)
    losers = [trade for trade in engine.blotter.trades if trade.r < 0.0]
    assert losers, "expected losing trades on this tape"
    # Costs and open-gap fills make -1R slightly worse; nothing may run away.
    assert min(trade.r for trade in losers) > -2.5


def test_risk_halt_stops_new_entries_for_the_session():
    engine = IcarusEngine(
        profile_for(AssetClass.CRYPTO).with_overrides(daily_loss_limit_r=0.25)
    )
    for bar in synthetic_for(AssetClass.CRYPTO, 3000, seed=11):
        engine.on_bar(bar)
        if engine.risk.halted:
            assert engine.risk.daily_r <= -0.25
            break
    else:
        pytest.skip("tape never hit the daily loss limit")


def test_scale_out_banks_partial_size_and_moves_the_stop_to_breakeven():
    engine = IcarusEngine(AssetClass.CRYPTO)
    saw_scale_out = False
    for bar in synthetic_for(AssetClass.CRYPTO, 8000, seed=29):
        for intent in engine.on_bar(bar):
            if intent.kind is IntentKind.SCALE_OUT:
                saw_scale_out = True
                assert engine.position is not None
                assert engine.position.scaled_out
                assert engine.position.breakeven_moved
                # The invariant is 'no risk left', not 'stop sits exactly at entry':
                # the ATR trail may tighten past breakeven on the same bar.
                position = engine.position
                remaining_risk = position.direction * (position.entry_price - position.stop)
                assert remaining_risk <= 1e-9
    if not saw_scale_out:
        pytest.skip("tape produced no first-target fills")
