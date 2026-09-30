from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tools.github_native_ai_openai import ModelResponse
from tools.github_native_local_model import LOCAL_MODEL_ID
from tools.github_native_local_model_canary import (
    build_canary_request,
    run_canary,
)


UTC = timezone.utc


def test_canary_request_is_non_executing_and_structured() -> None:
    request = build_canary_request()
    assert request.lane == "aion"
    assert request.model == LOCAL_MODEL_ID
    assert request.reasoning_effort == "local"
    assert "execution_authorized=false" in request.instructions
    assert "CANARY_OK" in request.input_text


def test_canary_artifact_truthfully_marks_local_zero_cost_inference(tmp_path: Path) -> None:
    output = tmp_path / "canary.json"
    fixed_now = datetime(2026, 9, 30, 21, 0, tzinfo=UTC)

    def fake_runner(request, *, binary, model, timeout_seconds=180):
        return ModelResponse(
            response_id="local-proof",
            status="completed",
            payload={
                "lane": "aion",
                "summary": "Local model canary succeeded.",
                "net_new_delta": "CANARY_OK",
                "data_gaps": [],
                "conflicts": [],
                "execution_authorized": False,
            },
        )

    result = run_canary(
        Path("/runtime/llama-cli"),
        Path("/models/qwen.gguf"),
        output,
        model_runner=fake_runner,
        now_fn=lambda: fixed_now,
    )

    assert result == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "omega-stack-local-model-canary-v1"
    assert payload["inference_backend"] == "local_gguf"
    assert payload["model"] == LOCAL_MODEL_ID
    assert payload["response_id"] == "local-proof"
    assert payload["response_status"] == "completed"
    assert payload["paid_api_call_made"] is False
    assert payload["api_credential_required"] is False
    assert payload["execution_authorized"] is False
    assert payload["payload"]["net_new_delta"] == "CANARY_OK"
