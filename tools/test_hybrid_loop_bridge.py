from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools import hybrid_loop_bridge as bridge


def registry() -> dict:
    return {
        "schema_version": "icarus-hybrid-loop-registry-v2",
        "fabric_id": bridge.FABRIC_ID,
        "fabric_activated_at_utc": "2026-10-04T19:02:00Z",
        "execution_authorized": False,
        "backfill_policy": {"order": "OLDEST_UNRESOLVED_FIRST"},
        "active_schedule": {
            "github_dispatch_minutes_local": {
                "robustness_guardian": 0,
                "advanced_csv": 10,
                "alpha_synthesis": 20,
                "microstructure_sensor_grid": 30,
            }
        },
        "lanes": {
            "robustness_guardian": {"title": "Robustness Guardian Evolution", "automation_id": "a", "project_scope": "ICARUS", "current_state": "ACTIVE"},
            "advanced_csv": {"title": "Advanced CSV Data Collector", "automation_id": "b", "project_scope": "ICARUS", "current_state": "ACTIVE"},
            "alpha_synthesis": {"title": "Alpha Synthesis Evolution", "automation_id": "c", "project_scope": "ICARUS", "current_state": "ACTIVE"},
            "microstructure_sensor_grid": {"title": "Microstructure Sensor Grid", "automation_id": "d", "project_scope": "ICARUS", "current_state": "ACTIVE"},
            "history": {"title": "Historical", "automation_id": "h", "project_scope": "H", "current_state": "HISTORICAL_DISABLED"},
        },
    }


class HybridBridgeTests(unittest.TestCase):
    def test_schedule_mapping(self) -> None:
        r = registry()
        self.assertEqual(bridge.select_lanes(r, "schedule", "0 * * * *", ""), ["robustness_guardian"])
        self.assertEqual(bridge.select_lanes(r, "schedule", "10 * * * *", ""), ["advanced_csv"])
        self.assertEqual(bridge.select_lanes(r, "schedule", "20 * * * *", ""), ["alpha_synthesis"])
        self.assertEqual(bridge.select_lanes(r, "schedule", "30 * * * *", ""), ["microstructure_sensor_grid"])

    def test_unknown_schedule_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            bridge.select_lanes(registry(), "schedule", "40 * * * *", "")

    def test_manual_all_active_excludes_history(self) -> None:
        selected = bridge.select_lanes(registry(), "workflow_dispatch", "", "all_active")
        self.assertEqual(set(selected), {"robustness_guardian", "advanced_csv", "alpha_synthesis", "microstructure_sensor_grid"})

    def test_manual_historical_is_single_lane(self) -> None:
        self.assertEqual(bridge.select_lanes(registry(), "workflow_dispatch", "", "history"), ["history"])
        with self.assertRaises(ValueError):
            bridge.select_lanes(registry(), "workflow_dispatch", "", "all_historical")
        with self.assertRaises(ValueError):
            bridge.select_lanes(registry(), "workflow_dispatch", "", "all_registered")

    def test_integrated_schedule_selects_active_only(self) -> None:
        selected = bridge.select_lanes(registry(), "integrated_schedule", "", "all_active")
        self.assertEqual(set(selected), {"robustness_guardian", "advanced_csv", "alpha_synthesis", "microstructure_sensor_grid"})

    def test_due_slots_start_after_fabric_activation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slots = bridge.due_slots_for_lane(
                root,
                registry(),
                "advanced_csv",
                datetime(2026, 10, 4, 20, 35, tzinfo=timezone.utc),
            )
            self.assertEqual(
                [bridge.z(x) for x in slots],
                ["2026-10-04T19:10:00Z", "2026-10-04T20:10:00Z"],
            )

    def test_integrated_slot_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = registry()
            now = datetime(2026, 10, 4, 20, 35, tzinfo=timezone.utc)
            slot = datetime(2026, 10, 4, 20, 0, tzinfo=timezone.utc)
            first = bridge.enqueue(root, reg, "robustness_guardian", "integrated_schedule", "100", "1", now, due_slot=slot)
            second = bridge.enqueue(root, reg, "robustness_guardian", "integrated_schedule", "101", "1", now, due_slot=slot)
            self.assertEqual(first["request_id"], second["request_id"])
            self.assertEqual(first["request_id"], "robustness_guardian-20261004T200000Z")
            self.assertEqual(first["due_slot_utc"], "2026-10-04T20:00:00Z")
            files = bridge.request_files(root, "robustness_guardian")
            self.assertEqual(len(files), 1)

    def test_due_slots_skip_existing_slots(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = registry()
            now = datetime(2026, 10, 4, 20, 35, tzinfo=timezone.utc)
            slot = datetime(2026, 10, 4, 19, 0, tzinfo=timezone.utc)
            bridge.enqueue(root, reg, "robustness_guardian", "integrated_schedule", "100", "1", now, due_slot=slot)
            slots = bridge.due_slots_for_lane(root, reg, "robustness_guardian", now)
            self.assertEqual([bridge.z(x) for x in slots], ["2026-10-04T20:00:00Z"])

    def test_result_requires_full_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_id = "req"
            path = root / bridge.result_path_for("robustness_guardian", request_id)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "schema_version": bridge.RESULT_SCHEMA,
                "fabric_id": bridge.FABRIC_ID,
                "request_id": request_id,
                "lane": "robustness_guardian",
                "automation_id": "a",
                "execution_authorized": False,
            }))
            self.assertFalse(bridge.result_valid(root, "robustness_guardian", "a", request_id))

    def test_valid_result_resolves_request(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lane = "robustness_guardian"
            request_id = "robustness_guardian-20261004T180000Z"
            req_dir = root / bridge.request_dir_for(lane)
            req_dir.mkdir(parents=True)
            (req_dir / (request_id + ".json")).write_text(json.dumps({"request_id": request_id, "due_slot_utc": "2026-10-04T18:00:00Z"}))
            result = {
                "schema_version": bridge.RESULT_SCHEMA,
                "fabric_id": bridge.FABRIC_ID,
                "request_id": request_id,
                "lane": lane,
                "automation_id": "a",
                "started_at_utc": "2026-10-04T18:05:00Z",
                "completed_at_utc": "2026-10-04T18:10:00Z",
                "outcome": "NO_MATERIAL_DELTA",
                "substantive_work_performed": True,
                "summary": "checked",
                "evidence": [],
                "research_receipt_paths": [],
                "event_paths": [],
                "blockers": [],
                "backfilled_request_ids": [],
                "execution_authorized": False,
            }
            result_path = root / bridge.result_path_for(lane, request_id)
            result_path.parent.mkdir(parents=True)
            result_path.write_text(json.dumps(result))
            self.assertEqual(bridge.unresolved_requests(root, lane, "a"), [])

    def test_enqueue_is_immutable_and_records_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = registry()
            now1 = datetime(2026, 10, 4, 19, 5, tzinfo=timezone.utc)
            slot1 = datetime(2026, 10, 4, 19, 0, tzinfo=timezone.utc)
            first = bridge.enqueue(root, reg, "robustness_guardian", "integrated_schedule", "10", "1", now1, due_slot=slot1)
            now2 = datetime(2026, 10, 4, 20, 5, tzinfo=timezone.utc)
            slot2 = datetime(2026, 10, 4, 20, 0, tzinfo=timezone.utc)
            second = bridge.enqueue(root, reg, "robustness_guardian", "integrated_schedule", "11", "1", now2, due_slot=slot2)
            self.assertIn(first["request_id"], second["prior_unresolved_request_ids"])
            self.assertTrue((root / bridge.request_dir_for("robustness_guardian") / (first["request_id"] + ".json")).exists())
            self.assertTrue((root / bridge.request_dir_for("robustness_guardian") / (second["request_id"] + ".json")).exists())

    def test_execution_authorized_must_be_false(self) -> None:
        r = registry()
        r["execution_authorized"] = True
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / bridge.REGISTRY
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps(r))
            with self.assertRaises(ValueError):
                bridge.load_registry(Path(td))


if __name__ == "__main__":
    unittest.main()
