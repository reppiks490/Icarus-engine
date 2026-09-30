import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from restored_five_durability_watchdog import (
    compare_run_ids,
    expected_slot,
    finalization_can_repair,
    monitor_missing_evidence,
    monitor_missing_receipt,
    reconcile_lane,
)


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj) + "\n")


class WatchdogTests(unittest.TestCase):
    def test_compare_run_ids(self):
        self.assertEqual(compare_run_ids("x-20260930T210500Z", "x-20260930T200500Z"), 1)
        self.assertEqual(compare_run_ids("x-20260930T200500Z", "x-20260930T210500Z"), -1)
        self.assertEqual(compare_run_ids("x-20260930T210500Z", "x-20260930T210500Z"), 0)

    def test_finalization_never_regresses_newer_heartbeat_even_with_matching_startup(self):
        self.assertFalse(
            finalization_can_repair(
                "lane-20260930T200500Z",
                "lane-20260930T200500Z",
                "lane-20260930T210500Z",
            )
        )

    def test_finalization_can_advance_older_heartbeat(self):
        self.assertTrue(
            finalization_can_repair(
                None,
                "lane-20260930T210500Z",
                "lane-20260930T200500Z",
            )
        )

    def test_mismatched_live_startup_blocks_finalization_repair(self):
        self.assertFalse(
            finalization_can_repair(
                "lane-20260930T212500Z",
                "lane-20260930T202500Z",
                "lane-20260930T202500Z",
            )
        )

    def test_expected_slot_respects_grace(self):
        now = datetime(2026, 9, 30, 21, 10, tzinfo=timezone.utc)
        self.assertEqual(expected_slot(now, 5, 12), datetime(2026, 9, 30, 20, 5, tzinfo=timezone.utc))
        now2 = datetime(2026, 9, 30, 21, 17, tzinfo=timezone.utc)
        self.assertEqual(expected_slot(now2, 5, 12), datetime(2026, 9, 30, 21, 5, tzinfo=timezone.utc))

    def test_v56_startup_uses_shorter_stale_window(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            root = repo / "lane"
            write_json(root / "startup_state.json", {
                "schema_version": "scheduler-startup-v5.6",
                "RUN_ID": "lane-20260930T200500Z",
                "RUN_STATUS": "STARTED",
            })
            write_json(root / "finalization_state.json", {})
            write_json(root / "heartbeat.json", {})
            changed = reconcile_lane(
                repo, "lane", "lane", "sched", 30, 12,
                datetime(2026, 9, 30, 20, 18, tzinfo=timezone.utc),
            )
            self.assertIn("lane/startup_state.json", changed)
            self.assertEqual(json.loads((root / "startup_state.json").read_text())["RUN_STATUS"], "EMPTY_READY")
            self.assertEqual(json.loads((root / "heartbeat.json").read_text())["RUN_STATUS"], "PARTIAL_PERSISTENCE")

    def test_v55_startup_keeps_30_minute_window(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            root = repo / "lane"
            write_json(root / "startup_state.json", {
                "schema_version": "scheduler-startup-v5.5",
                "RUN_ID": "lane-20260930T200500Z",
                "RUN_STATUS": "STARTED",
            })
            write_json(root / "finalization_state.json", {})
            write_json(root / "heartbeat.json", {})
            changed = reconcile_lane(
                repo, "lane", "lane", "sched", 30, 12,
                datetime(2026, 9, 30, 20, 18, tzinfo=timezone.utc),
            )
            self.assertEqual(changed, [])
            self.assertEqual(json.loads((root / "startup_state.json").read_text())["RUN_STATUS"], "STARTED")

    def test_missing_receipt_incident_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            root = repo / "lane"
            write_json(root / "finalization_state.json", {
                "RUN_ID": "lane-20260930T200500Z",
                "RUN_STATUS": "RUN_PERSISTED",
            })
            now = datetime(2026, 9, 30, 21, 18, tzinfo=timezone.utc)
            first = monitor_missing_receipt(
                repo, "lane", "lane", "sched", 5, "lane", 12,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc), now,
            )
            second = monitor_missing_receipt(
                repo, "lane", "lane", "sched", 5, "lane", 12,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc), now,
            )
            self.assertEqual(first, ["lane/watchdog_incidents.jsonl"])
            self.assertEqual(second, [])
            lines=(root / "watchdog_incidents.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["record_type"], "MISSING_CANONICAL_RECEIPT")

    def test_incomplete_evidence_incident_requires_canonical_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            root = repo / "lane"
            expected = "lane-20260930T210500Z"
            write_json(root / "finalization_state.json", {
                "RUN_ID": expected,
                "RUN_STATUS": "RUN_PERSISTED",
            })
            write_json(root / "evidence_state.json", {
                "RUN_ID": "lane-20260930T200500Z",
                "EVIDENCE_STATUS": "EVIDENCE_VERIFIED",
            })
            changed = monitor_missing_evidence(
                repo, "lane", "lane", "sched", 5, "lane", 20,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 30, 21, 26, tzinfo=timezone.utc),
            )
            self.assertEqual(changed, ["lane/watchdog_incidents.jsonl"])
            incident=json.loads((root / "watchdog_incidents.jsonl").read_text().splitlines()[0])
            self.assertEqual(incident["record_type"], "EVIDENCE_PHASE_INCOMPLETE")
            self.assertTrue(incident["canonical_receipt_present"])

    def test_expected_run_id_with_invalid_receipt_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            root = repo / "lane"
            expected = "lane-20260930T210500Z"
            write_json(root / "finalization_state.json", {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": expected,
                "RUN_STATUS": "PARTIAL_PERSISTENCE",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            })
            changed = monitor_missing_receipt(
                repo, "lane", "lane", "sched", 5, "lane", 12,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 30, 21, 18, tzinfo=timezone.utc),
            )
            self.assertEqual(changed, ["lane/watchdog_incidents.jsonl"])
            incident = json.loads((root / "watchdog_incidents.jsonl").read_text().splitlines()[0])
            self.assertEqual(incident["record_type"], "MALFORMED_CANONICAL_RECEIPT")
            self.assertEqual(incident["observed_RUN_STATUS"], "PARTIAL_PERSISTENCE")

    def test_valid_v57_receipt_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            root = repo / "lane"
            expected = "lane-20260930T210500Z"
            write_json(root / "finalization_state.json", {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": expected,
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            })
            changed = monitor_missing_receipt(
                repo, "lane", "lane", "sched", 5, "lane", 12,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 30, 21, 18, tzinfo=timezone.utc),
            )
            self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
