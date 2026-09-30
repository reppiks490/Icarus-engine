import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from restored_five_native_liveness import (
    Control,
    Lane,
    expected_slots,
    persist_slot,
    receipt_path,
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
            activated_at_utc=datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc),
            grace_minutes=8,
            catchup_horizon_minutes=180,
            timezone="America/Chicago",
            lanes=(self.lane(),),
        )

    def test_slot_waits_for_grace(self):
        slots=list(expected_slots(self.control(), datetime(2026,9,30,22,12,tzinfo=timezone.utc)))
        self.assertEqual(slots, [])
        slots=list(expected_slots(self.control(), datetime(2026,9,30,22,13,tzinfo=timezone.utc)))
        self.assertEqual(slots[0][1], datetime(2026,9,30,22,5,tzinfo=timezone.utc))

    def test_missing_worker_receipt_creates_truthful_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            lane=self.lane()
            slot=datetime(2026,9,30,22,5,tzinfo=timezone.utc)
            out=persist_slot(root,self.control(),lane,slot,datetime(2026,9,30,22,13,tzinfo=timezone.utc))
            self.assertIsNotNone(out)
            payload=json.loads(out.read_text())
            self.assertEqual(payload["slot_status"],"FALLBACK_LIVENESS_ONLY")
            self.assertFalse(payload["substantive_work_claimed"])
            self.assertFalse(payload["execution_authorized"])

    def test_valid_worker_receipt_is_verified_not_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            lane=self.lane()
            slot=datetime(2026,9,30,22,5,tzinfo=timezone.utc)
            p=root/lane.worker_root/"finalization_state.json"
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({
                "schema_version":"scheduler-finalization-v5.7",
                "RUN_ID":"robustness-guardian-20260930T220500Z",
                "RUN_STATUS":"RUN_PERSISTED",
                "completion_semantics":"DURABILITY_RECEIPT_ONLY",
                "execution_authorized":False,
            }))
            out=persist_slot(root,self.control(),lane,slot,datetime(2026,9,30,22,13,tzinfo=timezone.utc))
            payload=json.loads(out.read_text())
            self.assertEqual(payload["slot_status"],"WORKER_RECEIPT_VERIFIED")

    def test_receipt_is_immutable_duplicate_suppressed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            lane=self.lane()
            slot=datetime(2026,9,30,22,5,tzinfo=timezone.utc)
            first=persist_slot(root,self.control(),lane,slot,datetime(2026,9,30,22,13,tzinfo=timezone.utc))
            second=persist_slot(root,self.control(),lane,slot,datetime(2026,9,30,22,14,tzinfo=timezone.utc))
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertTrue(receipt_path(root,lane,slot).exists())


if __name__ == "__main__":
    unittest.main()
