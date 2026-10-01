from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from tools.restored_five_local_shadow_job import (
    LANES,
    main,
    reconcile_all,
    reconcile_late_verifications,
    reconcile_pre_hardening_summaries,
    select_pending,
    select_pending_batch,
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


    def test_select_pending_batch_is_bounded_and_oldest_first(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                ("apex_council", "20260930T224500Z"),
                ("flow_microstructure", "20260930T223500Z"),
                ("alpha_synthesis", "20260930T222500Z"),
                ("advanced_csv", "20260930T221500Z"),
                ("robustness_guardian", "20260930T220500Z"),
            ]
            for lane, slot in rows:
                p = root / "automation_intelligence/restored_five_native/receipts" / lane / f"{slot}.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("{}", encoding="utf-8")
            batch = select_pending_batch(root, limit=3)
            self.assertEqual(
                [(item.lane, item.slot_id) for item in batch],
                [
                    ("robustness_guardian", "20260930T220500Z"),
                    ("advanced_csv", "20260930T221500Z"),
                    ("alpha_synthesis", "20260930T222500Z"),
                ],
            )
            self.assertEqual(select_pending_batch(root, limit=0), [])


    def test_pre_hardening_summary_gets_separate_correction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slot = "20260930T223500Z"
            receipt = root / f"automation_intelligence/restored_five_native/receipts/flow_microstructure/{slot}.json"
            shadow = root / f"automation_intelligence/restored_five_native/shadow_outputs/flow_microstructure/{slot}.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            shadow.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(
                '{"slot_status":"WORKER_RECEIPT_VERIFIED","worker_receipt_status":"CHATGPT_CANONICAL_RECEIPT_PRESENT","expected_RUN_ID":"flow-20260930T223500Z","observed_worker_RUN_ID":"flow-20260930T223500Z","substantive_work_claimed":false,"execution_authorized":false}',
                encoding="utf-8",
            )
            shadow.write_text(
                '{"schema_version":"restored-five-local-shadow-v1","payload":{"summary":"No gaps or conflicts.","data_gaps":["SUBSTANTIVE_WORK_NOT_PROVEN"]}}',
                encoding="utf-8",
            )
            shadow_before = shadow.read_text()

            created = reconcile_pre_hardening_summaries(root)
            self.assertEqual(len(created), 1)
            payload = __import__("json").loads(created[0].read_text())
            self.assertEqual(
                payload["reconciliation_kind"],
                "PRE_HARDENING_SUMMARY_CORRECTION",
            )
            self.assertIn("Worker durability receipt verified.", payload["effective_summary"])
            self.assertIn(
                "Substantive work is not proven by this durability evidence.",
                payload["effective_summary"],
            )
            self.assertEqual(shadow.read_text(), shadow_before)
            self.assertFalse(payload["canonical_state_mutated"])
            self.assertFalse(payload["execution_authorized"])

            self.assertEqual(reconcile_pre_hardening_summaries(root), [])


    def test_reconcile_all_includes_pre_hardening_and_late_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slot = "20260930T223500Z"
            receipt = root / f"automation_intelligence/restored_five_native/receipts/flow_microstructure/{slot}.json"
            shadow = root / f"automation_intelligence/restored_five_native/shadow_outputs/flow_microstructure/{slot}.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            shadow.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(
                '{"slot_status":"WORKER_RECEIPT_VERIFIED","worker_receipt_status":"CHATGPT_CANONICAL_RECEIPT_PRESENT","expected_RUN_ID":"flow-20260930T223500Z","observed_worker_RUN_ID":"flow-20260930T223500Z","substantive_work_claimed":false,"execution_authorized":false}',
                encoding="utf-8",
            )
            shadow.write_text(
                '{"schema_version":"restored-five-local-shadow-v1","payload":{"summary":"No gaps or conflicts.","data_gaps":["SUBSTANTIVE_WORK_NOT_PROVEN"]}}',
                encoding="utf-8",
            )
            created = reconcile_all(root)
            self.assertEqual(len(created), 1)
            payload = __import__("json").loads(created[0].read_text())
            self.assertEqual(
                payload["reconciliation_kind"],
                "PRE_HARDENING_SUMMARY_CORRECTION",
            )

    def test_main_invokes_unified_reconciliation(self):
        source = inspect.getsource(main)
        self.assertIn("reconciled = reconcile_all(root)", source)
        self.assertNotIn("reconciled = reconcile_late_verifications(root)", source)


if __name__ == "__main__":
    unittest.main()
