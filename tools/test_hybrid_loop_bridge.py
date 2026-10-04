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
        "execution_authorized": False,
        "backfill_policy": {"order": "OLDEST_UNRESOLVED_FIRST"},
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
            request_id = "robustness_guardian-20261004T180000Z-gh-1-1"
            req_dir = root / bridge.request_dir_for(lane)
            req_dir.mkdir(parents=True)
            (req_dir / (request_id + ".json")).write_text(json.dumps({"request_id": request_id}))
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
            now1 = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)
            first = bridge.enqueue(root, reg, "robustness_guardian", "schedule", "10", "1", now1)
            now2 = datetime(2026, 10, 4, 19, 0, tzinfo=timezone.utc)
            second = bridge.enqueue(root, reg, "robustness_guardian", "schedule", "11", "1", now2)
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
