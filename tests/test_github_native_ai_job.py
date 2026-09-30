from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from tools.github_native_ai_dispatcher import load_control_plane
from tools.github_native_ai_job import select_pending_slot, select_slot, should_execute


UTC = timezone.utc


def test_dark_mode_scheduled_event_is_noop() -> None:
    control = load_control_plane(Path("."))
    assert control.mode == "DARK"
    assert should_execute(control, event_name="schedule", execute_model=True) is False


def test_manual_diagnostic_does_not_execute_model() -> None:
    control = load_control_plane(Path("."))
    assert should_execute(control, event_name="workflow_dispatch", execute_model=False) is False


def test_manual_explicit_canary_can_execute_while_dark() -> None:
    control = load_control_plane(Path("."))
    assert should_execute(control, event_name="workflow_dispatch", execute_model=True) is True


def test_scheduled_selection_never_runs_future_slot() -> None:
    control = load_control_plane(Path("."))
    now = datetime(2026, 9, 30, 12, 59, tzinfo=UTC)
    assert select_slot(control, now) is None


def test_scheduled_selection_accepts_recent_due_slot() -> None:
    control = load_control_plane(Path("."))
    now = datetime(2026, 9, 30, 13, 4, tzinfo=UTC)
    slot = select_slot(control, now)
    assert slot is not None
    assert slot.lane.name == "omega"
    assert slot.slot_id == "20260930T130000Z"


def test_manual_slot_must_match_requested_lane_boundary() -> None:
    control = load_control_plane(Path("."))
    slot = select_slot(
        control,
        datetime(2026, 9, 30, 13, 20, tzinfo=UTC),
        requested_lane="aion",
        requested_slot_utc="2026-09-30T13:36:00Z",
    )
    assert slot is not None
    assert slot.lane.name == "aion"
    assert slot.slot_id == "20260930T133600Z"


def test_manual_slot_rejects_wrong_lane_boundary() -> None:
    control = load_control_plane(Path("."))
    try:
        select_slot(
            control,
            datetime(2026, 9, 30, 13, 20, tzinfo=UTC),
            requested_lane="flow",
            requested_slot_utc="2026-09-30T13:36:00Z",
        )
    except ValueError as exc:
        assert "requested lane" in str(exc)
    else:
        raise AssertionError("expected lane mismatch to fail")


def test_scheduled_catchup_selects_oldest_unprocessed_slot_after_delay(tmp_path: Path) -> None:
    control = replace(
        load_control_plane(Path(".")),
        mode="SHADOW",
        activated_at_utc=datetime(2026, 9, 30, 12, 59, tzinfo=UTC),
        catchup_horizon_minutes=180,
    )
    slot = select_pending_slot(
        tmp_path,
        control,
        datetime(2026, 9, 30, 13, 19, tzinfo=UTC),
    )
    assert slot is not None
    assert slot.lane.name == "omega"
    assert slot.slot_id == "20260930T130000Z"


def test_scheduled_catchup_skips_terminal_slot_and_advances(tmp_path: Path) -> None:
    control = replace(
        load_control_plane(Path(".")),
        mode="SHADOW",
        activated_at_utc=datetime(2026, 9, 30, 12, 59, tzinfo=UTC),
        catchup_horizon_minutes=180,
    )
    omega_dir = (
        tmp_path
        / control.namespace_root
        / "lanes"
        / "omega"
        / "runs"
        / "20260930T130000Z"
    )
    omega_dir.mkdir(parents=True)
    (omega_dir / "done.json").write_text("{}\n", encoding="utf-8")

    slot = select_pending_slot(
        tmp_path,
        control,
        datetime(2026, 9, 30, 13, 19, tzinfo=UTC),
    )
    assert slot is not None
    assert slot.lane.name == "macro"
    assert slot.slot_id == "20260930T131200Z"


def test_scheduled_catchup_never_selects_pre_activation_slot(tmp_path: Path) -> None:
    control = replace(
        load_control_plane(Path(".")),
        mode="SHADOW",
        activated_at_utc=datetime(2026, 9, 30, 13, 5, tzinfo=UTC),
        catchup_horizon_minutes=180,
    )
    slot = select_pending_slot(
        tmp_path,
        control,
        datetime(2026, 9, 30, 13, 19, tzinfo=UTC),
    )
    assert slot is not None
    assert slot.lane.name == "macro"
    assert slot.slot_id == "20260930T131200Z"


def test_dark_control_has_no_scheduled_pending_slot(tmp_path: Path) -> None:
    control = load_control_plane(Path("."))
    assert control.mode == "DARK"
    assert select_pending_slot(
        tmp_path,
        control,
        datetime(2026, 9, 30, 13, 19, tzinfo=UTC),
    ) is None
