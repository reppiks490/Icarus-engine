from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.github_native_ai_dispatcher import (
    NAMESPACE_ROOT,
    load_control_plane,
    resolve_due_slot,
    terminal_artifact_exists,
)


UTC = timezone.utc


def _control() -> object:
    return load_control_plane(Path("."))


@pytest.mark.parametrize(
    ("when", "lane", "slot_id"),
    [
        ("2026-09-30T13:00:00+00:00", "omega", "20260930T130000Z"),
        ("2026-09-30T13:12:00+00:00", "macro", "20260930T131200Z"),
        ("2026-09-30T13:24:00+00:00", "flow", "20260930T132400Z"),
        ("2026-09-30T13:36:00+00:00", "aion", "20260930T133600Z"),
        ("2026-09-30T13:48:00+00:00", "daedalus", "20260930T134800Z"),
    ],
)
def test_resolves_exact_chicago_lane_boundaries(when: str, lane: str, slot_id: str) -> None:
    slot = resolve_due_slot(datetime.fromisoformat(when), _control(), tolerance_minutes=4)
    assert slot is not None
    assert slot.lane.name == lane
    assert slot.slot_id == slot_id
    assert slot.scheduled_utc.isoformat() == when


def test_tolerance_is_inclusive_at_four_minutes_and_exclusive_after() -> None:
    control = _control()

    inside = resolve_due_slot(datetime.fromisoformat("2026-09-30T13:04:00+00:00"), control, tolerance_minutes=4)
    outside = resolve_due_slot(datetime.fromisoformat("2026-09-30T13:05:00+00:00"), control, tolerance_minutes=4)

    assert inside is not None
    assert inside.lane.name == "omega"
    assert outside is None


def test_spring_forward_never_fabricates_nonexistent_chicago_hour() -> None:
    slot = resolve_due_slot(datetime.fromisoformat("2027-03-14T08:12:00+00:00"), _control(), tolerance_minutes=4)

    assert slot is not None
    assert slot.lane.name == "macro"
    assert slot.scheduled_local.isoformat() == "2027-03-14T03:12:00-05:00"
    assert slot.slot_id == "20270314T081200Z"


def test_fall_back_duplicate_wall_clock_slots_have_distinct_utc_ids() -> None:
    control = _control()
    first = resolve_due_slot(datetime.fromisoformat("2026-11-01T06:36:00+00:00"), control, tolerance_minutes=4)
    second = resolve_due_slot(datetime.fromisoformat("2026-11-01T07:36:00+00:00"), control, tolerance_minutes=4)

    assert first is not None and second is not None
    assert first.lane.name == second.lane.name == "aion"
    assert first.scheduled_local.strftime("%H:%M") == second.scheduled_local.strftime("%H:%M") == "01:36"
    assert first.scheduled_local.utcoffset() != second.scheduled_local.utcoffset()
    assert first.slot_id == "20261101T063600Z"
    assert second.slot_id == "20261101T073600Z"


def test_control_plane_is_exactly_five_fail_closed_lanes() -> None:
    control = _control()

    assert control.execution_authorized is False
    assert [(lane.name, lane.minute) for lane in control.lanes] == [
        ("omega", 0),
        ("macro", 12),
        ("flow", 24),
        ("aion", 36),
        ("daedalus", 48),
    ]


@pytest.mark.parametrize("kind", ["runs", "outputs", "failures"])
def test_terminal_artifact_suppresses_duplicate_slot(tmp_path: Path, kind: str) -> None:
    control = _control()
    slot = resolve_due_slot(datetime.fromisoformat("2026-09-30T13:24:00+00:00"), control, tolerance_minutes=4)
    assert slot is not None

    terminal_dir = (
        tmp_path
        / NAMESPACE_ROOT
        / "lanes"
        / slot.lane.name
        / kind
        / slot.slot_id
    )
    terminal_dir.mkdir(parents=True)
    (terminal_dir / "existing.json").write_text("{}\n", encoding="utf-8")

    assert terminal_artifact_exists(tmp_path, slot) is True


def test_empty_slot_is_not_suppressed(tmp_path: Path) -> None:
    slot = resolve_due_slot(datetime.fromisoformat("2026-09-30T13:48:00+00:00"), _control(), tolerance_minutes=4)
    assert slot is not None
    assert terminal_artifact_exists(tmp_path, slot) is False
