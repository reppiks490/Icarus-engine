from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.github_native_ai_openai import ModelResponse
from tools.github_native_local_model import LOCAL_MODEL_ID
from tools.restored_five_local_shadow import (
    ALLOWED_LANES,
    build_shadow_request,
    derive_receipt_facts,
    enforce_evidence_guards,
    run_shadow,
)

UTC = timezone.utc


def sample_receipt() -> dict[str, object]:
    return {
        "schema_version": "restored-five-native-liveness-receipt-v1",
        "lane": "robustness_guardian",
        "slot_status": "FALLBACK_LIVENESS_ONLY",
        "worker_receipt_status": "WORKER_RECEIPT_MISSING",
        "substantive_work_claimed": False,
        "execution_authorized": False,
    }


class RestoredFiveLocalShadowTests(unittest.TestCase):
    def test_shadow_request_is_read_only_and_non_executing(self):
        req = build_shadow_request("robustness_guardian", sample_receipt())
        self.assertEqual(req.model, LOCAL_MODEL_ID)
        self.assertEqual(req.reasoning_effort, "local")
        self.assertIn("read-only", req.instructions)
        self.assertIn("AUTHORITATIVE_FACTS", req.instructions)
        self.assertIn("execution_authorized=false", req.instructions)
        self.assertIn("summary under 350 characters", req.instructions)
        self.assertIn("FALLBACK_LIVENESS_ONLY", req.input_text)

    def test_shadow_rejects_unknown_lane(self):
        with self.assertRaisesRegex(ValueError, "unsupported restored-five lane"):
            build_shadow_request("unknown", sample_receipt())

    def test_all_five_restored_lanes_are_explicitly_allowed(self):
        self.assertEqual(
            ALLOWED_LANES,
            {
                "robustness_guardian",
                "advanced_csv",
                "alpha_synthesis",
                "flow_microstructure",
                "apex_council",
            },
        )

    def test_shadow_artifact_binds_input_hash_and_never_mutates_canonical_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_path = root / "receipt.json"
            output_path = root / "shadow.json"
            input_path.write_text(
                json.dumps(sample_receipt(), sort_keys=True),
                encoding="utf-8",
            )

            def fake_runner(request, *, binary, model, timeout_seconds=180):
                return ModelResponse(
                    response_id="local-shadow-proof",
                    status="completed",
                    payload={
                        "lane": "robustness_guardian",
                        "summary": "Fallback-only receipt; worker completion is not proven.",
                        "net_new_delta": "SHADOW_ASSESSMENT_ONLY",
                        "data_gaps": ["CANONICAL_WORKER_RECEIPT_MISSING"],
                        "conflicts": [],
                        "execution_authorized": False,
                    },
                )

            result = run_shadow(
                "robustness_guardian",
                input_path,
                output_path,
                binary=Path("/runtime/llama-completion"),
                model=Path("/models/qwen.gguf"),
                model_runner=fake_runner,
                now_fn=lambda: datetime(2026, 9, 30, 23, 0, tzinfo=UTC),
            )
            self.assertEqual(result, output_path)
            artifact = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["schema_version"], "restored-five-local-shadow-v1")
            self.assertFalse(artifact["canonical_state_mutated"])
            self.assertFalse(artifact["execution_authorized"])
            self.assertFalse(artifact["paid_api_call_made"])
            self.assertFalse(artifact["payload"]["execution_authorized"])
            self.assertEqual(
                artifact["payload"]["net_new_delta"],
                "SHADOW_ASSESSMENT_ONLY",
            )
            self.assertIn("FALLBACK_LIVENESS_ONLY", artifact["payload"]["data_gaps"])
            self.assertIn(
                "WORKER_RECEIPT_NOT_VERIFIED:WORKER_RECEIPT_MISSING",
                artifact["payload"]["data_gaps"],
            )
            self.assertIn(
                "SUBSTANTIVE_WORK_NOT_PROVEN",
                artifact["payload"]["data_gaps"],
            )
            self.assertEqual(len(artifact["input_sha256"]), 64)

    def test_deterministic_guards_force_fallback_gaps(self):
        source = {
            **sample_receipt(),
            "expected_RUN_ID": "robustness-guardian-20260930T220500Z",
            "observed_worker_RUN_ID": "robustness-guardian-20260930T170500Z",
        }
        model_payload = {
            "lane": "robustness_guardian",
            "summary": "Model omitted the obvious gap.",
            "net_new_delta": "0",
            "data_gaps": [],
            "conflicts": [],
            "execution_authorized": False,
        }
        guarded = enforce_evidence_guards(source, model_payload)
        self.assertEqual(guarded["net_new_delta"], "SHADOW_ASSESSMENT_ONLY")
        self.assertIn("FALLBACK_LIVENESS_ONLY", guarded["data_gaps"])
        self.assertIn(
            "WORKER_RECEIPT_NOT_VERIFIED:WORKER_RECEIPT_MISSING",
            guarded["data_gaps"],
        )
        self.assertIn("SUBSTANTIVE_WORK_NOT_PROVEN", guarded["data_gaps"])
        self.assertIn(
            "OBSERVED_WORKER_RUN_ID_DIFFERS_FROM_EXPECTED",
            guarded["conflicts"],
        )
        self.assertFalse(guarded["execution_authorized"])

    def test_deterministic_receipt_facts_are_authoritative(self):
        receipt = sample_receipt() | {
            "expected_RUN_ID": "robustness-guardian-20260930T220500Z",
            "observed_worker_RUN_ID": "robustness-guardian-20260930T170500Z",
            "observed_worker_RUN_STATUS": "RUN_PERSISTED",
        }
        facts = derive_receipt_facts(receipt)
        self.assertFalse(facts["run_id_match"])
        self.assertTrue(facts["fallback_only"])
        self.assertFalse(facts["substantive_work_claimed"])
        self.assertFalse(facts["execution_authorized"])

        req = build_shadow_request("robustness_guardian", receipt)
        self.assertIn("AUTHORITATIVE_FACTS", req.instructions)
        self.assertIn('"run_id_match":false', req.input_text)

    def test_shadow_artifact_embeds_deterministic_facts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_path = root / "receipt.json"
            output_path = root / "shadow.json"
            receipt = sample_receipt() | {
                "expected_RUN_ID": "robustness-guardian-20260930T220500Z",
                "observed_worker_RUN_ID": "robustness-guardian-20260930T170500Z",
            }
            input_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

            def fake_runner(request, *, binary, model, timeout_seconds=180):
                return ModelResponse(
                    response_id="local-grounded-proof",
                    status="completed",
                    payload={
                        "lane": "robustness_guardian",
                        "summary": "Machine facts show an older observed worker RUN_ID.",
                        "net_new_delta": "SHADOW_ASSESSMENT_ONLY",
                        "data_gaps": ["SUBSTANTIVE_WORK_NOT_PROVEN"],
                        "conflicts": ["EXPECTED_AND_OBSERVED_RUN_ID_DIFFER"],
                        "execution_authorized": False,
                    },
                )

            run_shadow(
                "robustness_guardian",
                input_path,
                output_path,
                binary=Path("/runtime/llama-completion"),
                model=Path("/models/qwen.gguf"),
                model_runner=fake_runner,
                now_fn=lambda: datetime(2026, 9, 30, 23, 0, tzinfo=UTC),
            )
            artifact = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(artifact["deterministic_facts"]["run_id_match"])
            self.assertTrue(artifact["deterministic_facts"]["fallback_only"])


if __name__ == "__main__":
    unittest.main()
