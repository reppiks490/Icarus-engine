from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.restored_five_local_shadow_job import LANES, select_pending


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


if __name__ == "__main__":
    unittest.main()
