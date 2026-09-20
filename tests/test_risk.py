import pytest

from icarus.config import AssetClass, profile_for
from icarus.risk import RiskManager, build_risk_envelope


def manager(**overrides):
    profile = profile_for(AssetClass.FUTURES).with_overrides(**overrides)
    return RiskManager(profile), profile


def test_size_is_risk_budget_divided_by_stop_distance():
    risk, profile = manager(risk_per_trade=0.01)
    result = risk.size_for(equity=100_000.0, entry_price=100.0, stop_price=98.0, bar_index=0)
    assert result.allowed
    assert result.risk_amount == pytest.approx(1_000.0)
    assert result.size == pytest.approx(500.0)          # 1000 / 2.0
    assert result.stop_distance == pytest.approx(2.0)


def test_wider_stops_buy_smaller_size():
    risk, _ = manager(risk_per_trade=0.01)
    tight = risk.size_for(100_000.0, 100.0, 99.0, 0).size
    wide = risk.size_for(100_000.0, 100.0, 96.0, 0).size
    assert wide == pytest.approx(tight / 4.0)


def test_degenerate_and_empty_accounts_are_refused():
    risk, _ = manager()
    assert not risk.size_for(100_000.0, 100.0, 100.0, 0).allowed
    assert risk.size_for(100_000.0, 100.0, 100.0, 0).reason == "degenerate-stop"
    assert not risk.size_for(0.0, 100.0, 98.0, 0).allowed


def test_daily_loss_limit_halts_the_session():
    risk, _ = manager(daily_loss_limit_r=2.0, cooldown_bars_after_exit=0)
    risk.register_exit(-1.0, bar_index=1)
    assert not risk.halted
    risk.register_exit(-1.2, bar_index=2)
    assert risk.halted and "daily-loss-limit" in risk.halt_reason
    assert not risk.size_for(100_000.0, 100.0, 98.0, 10).allowed


def test_session_roll_clears_the_daily_halt():
    risk, _ = manager(daily_loss_limit_r=1.0, cooldown_bars_after_exit=0)
    risk.register_exit(-1.5, bar_index=1)
    assert risk.halted
    risk.roll_session("2026-01-06")
    assert not risk.halted and risk.daily_r == 0.0


def test_losing_streak_halves_risk_and_a_win_restores_it():
    risk, profile = manager(consecutive_loss_throttle=3, cooldown_bars_after_exit=0,
                            daily_loss_limit_r=99.0)
    base = risk.risk_fraction
    for index in range(3):
        risk.register_exit(-1.0, bar_index=index)
    assert risk.consecutive_losses == 3
    assert risk.risk_fraction == pytest.approx(base / 2.0)
    risk.register_exit(1.0, bar_index=4)
    assert risk.consecutive_losses == 0
    assert risk.risk_fraction == pytest.approx(base)


def test_risk_fraction_is_capped():
    risk, _ = manager(risk_per_trade=0.05, max_risk_per_trade=0.01)
    assert risk.risk_fraction == pytest.approx(0.01)


def test_cooldown_blocks_re_entry_immediately_after_an_exit():
    risk, _ = manager(cooldown_bars_after_exit=3, daily_loss_limit_r=99.0)
    risk.register_exit(0.5, bar_index=10)
    assert risk.in_cooldown(12)
    assert risk.size_for(100_000.0, 100.0, 98.0, 12).reason == "cooldown"
    assert not risk.in_cooldown(13)
    assert risk.size_for(100_000.0, 100.0, 98.0, 13).allowed


def test_risk_envelope_parks_the_stop_beyond_the_raid_extreme():
    profile = profile_for(AssetClass.FUTURES).with_overrides(
        stop_buffer_atr=0.5, first_target_r=1.0, runner_target_r=3.0
    )
    stop, risk_unit, first, runner = build_risk_envelope(
        profile, direction=1, entry_price=100.0, stop_anchor=99.0, atr=2.0
    )
    assert stop == pytest.approx(98.0)                  # 99.0 - 0.5 * 2.0
    assert risk_unit == pytest.approx(2.0)
    assert first == pytest.approx(102.0)
    assert runner == pytest.approx(106.0)


def test_risk_envelope_is_mirrored_for_shorts():
    profile = profile_for(AssetClass.FUTURES).with_overrides(stop_buffer_atr=0.5)
    stop, risk_unit, first, runner = build_risk_envelope(
        profile, direction=-1, entry_price=100.0, stop_anchor=101.0, atr=2.0
    )
    assert stop == pytest.approx(102.0)
    assert risk_unit == pytest.approx(2.0)
    assert first < 100.0 and runner < first


def test_degenerate_geometry_falls_back_to_an_atr_stop():
    profile = profile_for(AssetClass.FUTURES).with_overrides(stop_buffer_atr=0.5)
    # Entry printed exactly at the anchor: the raid-extreme stop has zero width.
    stop, risk_unit, _, _ = build_risk_envelope(
        profile, direction=1, entry_price=100.0, stop_anchor=100.0, atr=2.0
    )
    assert risk_unit == pytest.approx(1.0)              # 0.5 * ATR fallback
    assert stop == pytest.approx(99.0)
