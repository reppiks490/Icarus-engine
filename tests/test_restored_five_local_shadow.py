from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.github_native_ai_openai import ModelResponse
from tools.github_native_local_model import LOCAL_MODEL_ID
from tools.restored_five_local_shadow import (
    ALLOWED_LANES,
    build_shadow_request,
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


def test_shadow_request_is_read_only_and_non_executing() -> None:
    req = build_shadow_request("robustness_guardian", sample_receipt())
    assert req.model == LOCAL_MODEL_ID
    assert req.reasoning_effort == "local"
    assert "read-only" in req.instructions
    assert "execution_authorized=false" in req.instructions
    assert "FALLBACK_LIVENESS_ONLY" in req.input_text


def test_shadow_rejects_unknown_lane() -> None:
    with pytest.raises(ValueError, match="unsupported restored-five lane"):
        build_shadow_request("unknown", sample_receipt())


def test_all_five_restored_lanes_are_explicitly_allowed() -> None:
    assert ALLOWED_LANES == {
        "robustness_guardian",
        "advanced_csv",
        "alpha_synthesis",
        "flow_microstructure",
        "apex_council",
    }


def test_shadow_artifact_binds_input_hash_and_never_mutates_canonical_state(tmp_path: Path) -> None:
    input_path = tmp_path / "receipt.json"
    output_path = tmp_path / "shadow.json"
    input_path.write_text(json.dumps(sample_receipt(), sort_keys=True), encoding="utf-8")

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
    assert result == output_path
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "restored-five-local-shadow-v1"
    assert artifact["canonical_state_mutated"] is False
    assert artifact["execution_authorized"] is False
    assert artifact["paid_api_call_made"] is False
    assert artifact["payload"]["execution_authorized"] is False
    assert len(artifact["input_sha256"]) == 64
