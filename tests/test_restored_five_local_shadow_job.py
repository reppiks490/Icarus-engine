from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.restored_five_local_shadow_job import (
    LANES,
    reconcile_late_verifications,
    select_pending,
)


class RestoredFiveLocalShadowJobTests(unittest.TestCase):
    def test_selects_oldest_pending_receipt_across_lanes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for lane, slot in [
                ("flow_microstructure", "20260930T223500Z"),
                ("robustness_guardian", "20260930T220500Z"),
                ("advanced_csv", "20260930T221500Z"),
            ]:
                p = root / "automation_intelligence/restored_five_native/receipts" / lane / f"{slot}.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("{}", encoding="utf-8")

            pending = select_pending(root)
            self.assertIsNotNone(pending)
            self.assertEqual(pending.lane, "robustness_guardian")
            self.assertEqual(pending.slot_id, "20260930T220500Z")

    def test_skips_already_shadowed_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt = root / "automation_intelligence/restored_five_native/receipts/robustness_guardian/20260930T220500Z.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text("{}", encoding="utf-8")
            output = root / "automation_intelligence/restored_five_native/shadow_outputs/robustness_guardian/20260930T220500Z.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("{}", encoding="utf-8")
            self.assertIsNone(select_pending(root))

    def test_lane_order_is_stable_and_complete(self):
        self.assertEqual(
            LANES,
            (
                "robustness_guardian",
                "advanced_csv",
                "alpha_synthesis",
                "flow_microstructure",
                "apex_council",
            ),
        )


    def test_late_verification_creates_immutable_reconciliation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slot = "20260930T221500Z"
            receipt = root / f"automation_intelligence/restored_five_native/receipts/advanced_csv/{slot}.json"
            shadow = root / f"automation_intelligence/restored_five_native/shadow_outputs/advanced_csv/{slot}.json"
            late = root / f"automation_intelligence/restored_five_native/late_verifications/advanced_csv/{slot}.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            shadow.parent.mkdir(parents=True, exist_ok=True)
            late.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(
                '{"expected_RUN_ID":"advanced-csv-20260930T221500Z","slot_status":"FALLBACK_LIVENESS_ONLY"}',
                encoding="utf-8",
            )
            shadow.write_text(
                '{"schema_version":"restored-five-local-shadow-v1","payload":{"data_gaps":["WORKER_RECEIPT_MISSING"]}}',
                encoding="utf-8",
            )
            late.write_text(
                '{"verification_status":"LATE_WORKER_RECEIPT_VERIFIED","observed_worker_RUN_ID":"advanced-csv-20260930T221500Z","substantive_work_claimed":false}',
                encoding="utf-8",
            )
            receipt_before = receipt.read_text()
            shadow_before = shadow.read_text()

            created = reconcile_late_verifications(root)
            self.assertEqual(len(created), 1)
            payload = __import__("json").loads(created[0].read_text())
            self.assertTrue(payload["effective_run_id_match"])
            self.assertEqual(
                payload["effective_worker_receipt_status"],
                "LATE_WORKER_RECEIPT_VERIFIED",
            )
            self.assertTrue(payload["original_fallback_preserved"])
            self.assertFalse(payload["canonical_state_mutated"])
            self.assertFalse(payload["execution_authorized"])
            self.assertEqual(receipt.read_text(), receipt_before)
            self.assertEqual(shadow.read_text(), shadow_before)

            second = reconcile_late_verifications(root)
            self.assertEqual(second, [])

    def test_reconciliation_waits_for_base_shadow(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slot = "20260930T221500Z"
            receipt = root / f"automation_intelligence/restored_five_native/receipts/advanced_csv/{slot}.json"
            late = root / f"automation_intelligence/restored_five_native/late_verifications/advanced_csv/{slot}.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            late.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(
                '{"expected_RUN_ID":"advanced-csv-20260930T221500Z"}',
                encoding="utf-8",
            )
            late.write_text(
                '{"verification_status":"LATE_WORKER_RECEIPT_VERIFIED","observed_worker_RUN_ID":"advanced-csv-20260930T221500Z"}',
                encoding="utf-8",
            )
            self.assertEqual(reconcile_late_verifications(root), [])


if __name__ == "__main__":
    unittest.main()
