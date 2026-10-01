import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from restored_five_native_liveness import (
    Control,
    Lane,
    expected_slots,
    late_verification_path,
    persist_late_verification,
    persist_slot,
    receipt_path,
    worker_receipt_status,
)


class NativeLivenessTests(unittest.TestCase):
    def lane(self):
        return Lane(
            name="robustness_guardian",
            title="Robustness Guardian Evolution",
            minute=5,
            scheduler_id="sched",
            worker_root="automation_intelligence/agent_fabric/robustness_guardian",
            run_prefix="robustness-guardian",
        )

    def control(self):
        return Control(
            repository="reppiks490/Icarus-engine",
            activated_at_utc=datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc),
            grace_minutes=8,
            catchup_horizon_minutes=180,
            timezone="America/Chicago",
            lanes=(self.lane(),),
        )

    def test_slot_waits_for_grace(self):
        slots = list(expected_slots(
            self.control(),
            datetime(2026, 9, 30, 22, 12, tzinfo=timezone.utc),
        ))
        self.assertEqual(slots, [])
        slots = list(expected_slots(
            self.control(),
            datetime(2026, 9, 30, 22, 13, tzinfo=timezone.utc),
        ))
        self.assertEqual(
            slots[0][1],
            datetime(2026, 9, 30, 22, 5, tzinfo=timezone.utc),
        )

    def test_missing_worker_receipt_creates_truthful_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lane = self.lane()
            slot = datetime(2026, 9, 30, 22, 5, tzinfo=timezone.utc)
            out = persist_slot(
                root,
                self.control(),
                lane,
                slot,
                datetime(2026, 9, 30, 22, 13, tzinfo=timezone.utc),
            )
            self.assertIsNotNone(out)
            payload = json.loads(out.read_text())
            self.assertEqual(payload["slot_status"], "FALLBACK_LIVENESS_ONLY")
            self.assertFalse(payload["substantive_work_claimed"])
            self.assertFalse(payload["execution_authorized"])

    def test_valid_worker_receipt_is_verified_not_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lane = self.lane()
            slot = datetime(2026, 9, 30, 22, 5, tzinfo=timezone.utc)
            p = root / lane.worker_root / "finalization_state.json"
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": "robustness-guardian-20260930T220500Z",
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            }))
            out = persist_slot(
                root,
                self.control(),
                lane,
                slot,
                datetime(2026, 9, 30, 22, 13, tzinfo=timezone.utc),
            )
            payload = json.loads(out.read_text())
            self.assertEqual(payload["slot_status"], "WORKER_RECEIPT_VERIFIED")

    def test_receipt_is_immutable_duplicate_suppressed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lane = self.lane()
            slot = datetime(2026, 9, 30, 22, 5, tzinfo=timezone.utc)
            first = persist_slot(
                root,
                self.control(),
                lane,
                slot,
                datetime(2026, 9, 30, 22, 13, tzinfo=timezone.utc),
            )
            second = persist_slot(
                root,
                self.control(),
                lane,
                slot,
                datetime(2026, 9, 30, 22, 14, tzinfo=timezone.utc),
            )
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertTrue(receipt_path(root, lane, slot).exists())

    def test_external_worker_receipt_can_be_verified(self):
        lane = Lane(
            name="advanced_csv",
            title="Advanced CSV Data Collector",
            minute=15,
            scheduler_id="csv-sched",
            worker_root="automation_intelligence/advanced_csv",
            run_prefix="advanced-csv",
            worker_repository="reppiks490/icarus-csv-evidence-lab",
        )
        control = Control(
            repository="reppiks490/Icarus-engine",
            activated_at_utc=datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc),
            grace_minutes=8,
            catchup_horizon_minutes=180,
            timezone="America/Chicago",
            lanes=(lane,),
        )
        expected = {
            "schema_version": "scheduler-finalization-v5.7",
            "RUN_ID": "advanced-csv-20260930T221500Z",
            "RUN_STATUS": "RUN_PERSISTED",
            "completion_semantics": "DURABILITY_RECEIPT_ONLY",
            "execution_authorized": False,
        }
        status, observed = worker_receipt_status(
            Path("."),
            control,
            lane,
            datetime(2026, 9, 30, 22, 15, tzinfo=timezone.utc),
            external_reader=lambda repository, path: ("FOUND", expected),
        )
        self.assertEqual(status, "CHATGPT_CANONICAL_RECEIPT_PRESENT")
        self.assertEqual(observed["RUN_ID"], expected["RUN_ID"])


    def test_fallback_can_gain_immutable_late_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lane = self.lane()
            control = self.control()
            slot = datetime(2026, 9, 30, 22, 5, tzinfo=timezone.utc)
            fallback = persist_slot(
                root, control, lane, slot,
                datetime(2026, 9, 30, 22, 13, tzinfo=timezone.utc),
            )
            self.assertIsNotNone(fallback)
            original_text = fallback.read_text()

            finalization = root / lane.worker_root / "finalization_state.json"
            finalization.parent.mkdir(parents=True, exist_ok=True)
            finalization.write_text(json.dumps({
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": "robustness-guardian-20260930T220500Z",
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            }))

            late = persist_late_verification(
                root, control, lane, slot,
                datetime(2026, 9, 30, 22, 20, tzinfo=timezone.utc),
            )
            self.assertIsNotNone(late)
            self.assertEqual(fallback.read_text(), original_text)
            payload = json.loads(late.read_text())
            self.assertEqual(
                payload["verification_status"],
                "LATE_WORKER_RECEIPT_VERIFIED",
            )
            self.assertEqual(
                payload["original_receipt"],
                str(receipt_path(root, lane, slot).relative_to(root)),
            )
            second = persist_late_verification(
                root, control, lane, slot,
                datetime(2026, 9, 30, 22, 21, tzinfo=timezone.utc),
            )
            self.assertIsNone(second)
            self.assertTrue(late_verification_path(root, lane, slot).exists())


    def test_workflow_retries_concurrent_main_pushes(self):
        workflow = Path(".github/workflows/restored-five-native-liveness.yml").read_text(encoding="utf-8")
        self.assertIn("for attempt in 1 2 3 4 5; do", workflow)
        self.assertIn("git fetch origin main", workflow)
        self.assertIn("git rebase origin/main", workflow)
        self.assertIn("Failed to persist native-liveness receipts after 5 optimistic push attempts.", workflow)

    def test_external_worker_404_equivalent_is_check_unavailable(self):
        lane = Lane(
            name="advanced_csv",
            title="Advanced CSV Data Collector",
            minute=15,
            scheduler_id="csv-sched",
            worker_root="automation_intelligence/advanced_csv",
            run_prefix="advanced-csv",
            worker_repository="reppiks490/icarus-csv-evidence-lab",
        )
        control = Control(
            repository="reppiks490/Icarus-engine",
            activated_at_utc=datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc),
            grace_minutes=8,
            catchup_horizon_minutes=180,
            timezone="America/Chicago",
            lanes=(lane,),
        )
        status, observed = worker_receipt_status(
            Path("."),
            control,
            lane,
            datetime(2026, 9, 30, 22, 15, tzinfo=timezone.utc),
            external_reader=lambda repository, path: ("UNAVAILABLE", {}),
        )
        self.assertEqual(status, "WORKER_RECEIPT_CHECK_UNAVAILABLE")
        self.assertEqual(observed, {})


    def test_watchdog_fallback_is_not_counted_as_chatgpt_worker_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lane = self.lane()
            control = self.control()
            slot = datetime(2026, 9, 30, 22, 5, tzinfo=timezone.utc)
            finalization = root / lane.worker_root / "finalization_state.json"
            finalization.parent.mkdir(parents=True, exist_ok=True)
            finalization.write_text(json.dumps({
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": "robustness-guardian-20260930T220500Z",
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "history_mode": "git_commit_finalization",
                "work_status": "WATCHDOG_FALLBACK_PERSISTED",
                "receipt_origin": "github_watchdog_stabilization_fallback",
                "worker_execution_observed": False,
                "payload": {"result": "SCHEDULER_WORKER_RECEIPT_MISSED"},
                "execution_authorized": False,
            }))

            status, observed = worker_receipt_status(root, control, lane, slot)
            self.assertEqual(status, "WATCHDOG_FALLBACK_RECEIPT_PRESENT")
            self.assertFalse(observed["worker_execution_observed"])

            out = persist_slot(
                root, control, lane, slot,
                datetime(2026, 9, 30, 22, 13, tzinfo=timezone.utc),
            )
            self.assertIsNotNone(out)
            payload = json.loads(out.read_text())
            self.assertEqual(payload["slot_status"], "FALLBACK_LIVENESS_ONLY")
            self.assertEqual(
                payload["worker_receipt_status"],
                "WATCHDOG_FALLBACK_RECEIPT_PRESENT",
            )
            self.assertFalse(payload["substantive_work_claimed"])

            late = persist_late_verification(
                root, control, lane, slot,
                datetime(2026, 9, 30, 22, 20, tzinfo=timezone.utc),
            )
            self.assertIsNone(late)


if __name__ == "__main__":
    unittest.main()
