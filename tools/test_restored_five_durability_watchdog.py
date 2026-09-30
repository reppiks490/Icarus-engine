import json
import subprocess
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from restored_five_durability_watchdog import (
    compare_run_ids,
    expected_slot,
    finalization_can_repair,
    finalization_repairable,
    heartbeat_mirror_valid,
    canonical_receipt_valid,
    historical_record_state,
    monitor_receipt_horizon,
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
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": expected,
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
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

    def test_malformed_receipt_does_not_trigger_evidence_alarm(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            root = repo / "lane"
            expected = "lane-20260930T210500Z"
            write_json(root / "finalization_state.json", {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": expected,
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "WRONG",
                "execution_authorized": False,
            })
            write_json(root / "evidence_state.json", {})
            changed = monitor_missing_evidence(
                repo, "lane", "lane", "sched", 5, "lane", 20,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 30, 21, 26, tzinfo=timezone.utc),
            )
            self.assertEqual(changed, [])

    def test_same_run_malformed_evidence_is_flagged(self):
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
            write_json(root / "evidence_state.json", {
                "schema_version": "scheduler-evidence-v5.6",
                "RUN_ID": expected,
                "EVIDENCE_STATUS": "EVIDENCE_VERIFIED",
                "execution_authorized": False,
            })
            changed = monitor_missing_evidence(
                repo, "lane", "lane", "sched", 5, "lane", 20,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 30, 21, 26, tzinfo=timezone.utc),
            )
            self.assertEqual(changed, ["lane/watchdog_incidents.jsonl"])
            incident = json.loads((root / "watchdog_incidents.jsonl").read_text().splitlines()[0])
            self.assertEqual(incident["record_type"], "MALFORMED_EVIDENCE_STATE")

    def test_valid_v57_evidence_is_accepted(self):
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
            write_json(root / "evidence_state.json", {
                "schema_version": "scheduler-evidence-v5.7",
                "RUN_ID": expected,
                "EVIDENCE_STATUS": "NO_NEW_EVIDENCE",
                "execution_authorized": False,
            })
            changed = monitor_missing_evidence(
                repo, "lane", "lane", "sched", 5, "lane", 20,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 30, 21, 26, tzinfo=timezone.utc),
            )
            self.assertEqual(changed, [])

    def test_heartbeat_binding_rejects_wrong_finalization_identity(self):
        heartbeat = {
            "schema_version": "scheduler-heartbeat-v5.7",
            "RUN_ID": "lane-20260930T210500Z",
            "RUN_STATUS": "RUN_PERSISTED",
            "finalization_commit_sha": "wrong-commit",
            "finalization_state_blob_sha": "wrong-blob",
            "execution_authorized": False,
        }
        self.assertFalse(
            heartbeat_mirror_valid(
                heartbeat,
                "lane-20260930T210500Z",
                "expected-commit",
                "expected-blob",
            )
        )

    def test_heartbeat_binding_accepts_exact_worker_or_watchdog_mirror(self):
        for schema in ("scheduler-heartbeat-v5.7", "scheduler-heartbeat-watchdog-v2"):
            heartbeat = {
                "schema_version": schema,
                "RUN_ID": "lane-20260930T210500Z",
                "RUN_STATUS": "RUN_PERSISTED",
                "finalization_commit_sha": "expected-commit",
                "finalization_state_blob_sha": "expected-blob",
                "execution_authorized": False,
            }
            self.assertTrue(
                heartbeat_mirror_valid(
                    heartbeat,
                    "lane-20260930T210500Z",
                    "expected-commit",
                    "expected-blob",
                )
            )

    def test_malformed_v57_finalization_is_not_repairable(self):
        self.assertFalse(
            finalization_repairable({
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": "lane-20260930T210500Z",
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "WRONG",
                "execution_authorized": False,
            })
        )

    def test_legacy_finalization_remains_repairable(self):
        self.assertTrue(
            finalization_repairable({
                "schema_version": "scheduler-finalization-v5.5",
                "RUN_ID": "lane-20260930T210500Z",
                "RUN_STATUS": "RUN_PERSISTED",
                "execution_authorized": False,
            })
        )

    def _init_git_repo(self, repo: Path):
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    def _commit_path(self, repo: Path, relpath: str, obj: dict, message: str):
        path = repo / relpath
        write_json(path, obj)
        subprocess.run(["git", "add", relpath], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True, text=True)

    def test_history_finds_valid_older_receipt_behind_newer_pointer(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_git_repo(repo)
            rel = "lane/finalization_state.json"
            old_run = "lane-20260930T212500Z"
            new_run = "lane-20260930T222500Z"
            self._commit_path(repo, rel, {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": old_run,
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            }, "old receipt")
            self._commit_path(repo, rel, {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": new_run,
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            }, "new receipt")
            self.assertEqual(
                historical_record_state(repo, rel, old_run, canonical_receipt_valid),
                "VALID",
            )

    def test_history_marks_same_run_malformed_when_no_valid_version_exists(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_git_repo(repo)
            rel = "lane/finalization_state.json"
            run_id = "lane-20260930T212500Z"
            self._commit_path(repo, rel, {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": run_id,
                "RUN_STATUS": "PARTIAL_PERSISTENCE",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            }, "bad receipt")
            self.assertEqual(
                historical_record_state(repo, rel, run_id, canonical_receipt_valid),
                "MALFORMED",
            )

    def test_horizon_monitor_detects_older_gap_even_with_newer_valid_pointer(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_git_repo(repo)
            rel = "lane/finalization_state.json"
            new_run = "lane-20260930T222500Z"
            self._commit_path(repo, rel, {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": new_run,
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            }, "new receipt only")
            changed = monitor_receipt_horizon(
                repo, "lane", "lane", "sched", 25, "lane", 12,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 30, 22, 40, tzinfo=timezone.utc),
                4,
            )
            self.assertEqual(changed, ["lane/watchdog_incidents.jsonl"])
            incidents = [
                json.loads(line)
                for line in (repo / "lane/watchdog_incidents.jsonl").read_text().splitlines()
            ]
            missing = [i for i in incidents if i["record_type"] == "MISSING_CANONICAL_RECEIPT"]
            self.assertEqual([i["RUN_ID"] for i in missing], ["lane-20260930T212500Z"])

    def test_horizon_builds_finalization_history_only_once(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            root = repo / "lane"
            write_json(root / "finalization_state.json", {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": "lane-20260930T222500Z",
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            })
            with mock.patch(
                "restored_five_durability_watchdog.git_json_history",
                return_value=[],
            ) as history:
                monitor_receipt_horizon(
                    repo, "lane", "lane", "sched", 25, "lane", 12,
                    datetime(2026, 9, 30, 19, 0, tzinfo=timezone.utc),
                    datetime(2026, 9, 30, 22, 40, tzinfo=timezone.utc),
                    4,
                )
                self.assertEqual(history.call_count, 1)

    def test_stabilization_receipt_intentionally_defers_evidence_alarm(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            root = repo / "lane"
            expected = "lane-20260930T210500Z"
            write_json(root / "finalization_state.json", {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": expected,
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "history_mode": "git_commit_finalization",
                "work_status": "BASELINE_PERSISTED",
                "payload": {
                    "result": "NO_NEW_EVIDENCE_YET",
                    "NEXT": "Durability proven; substantive evidence remains deferred during stabilization."
                },
                "execution_authorized": False,
            })
            write_json(root / "evidence_state.json", {})
            changed = monitor_missing_evidence(
                repo, "lane", "lane", "sched", 5, "lane", 20,
                datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 30, 21, 26, tzinfo=timezone.utc),
            )
            self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
