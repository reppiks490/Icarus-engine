from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from tools.github_native_ai_openai import ModelRequest, ModelResponse
from tools.github_native_local_model import (
    LLAMA_CPP_SHA256,
    LOCAL_MODEL_ID,
    MODEL_SHA256,
    run_local_model,
)

ModelRunner = Callable[..., ModelResponse]
UTC = timezone.utc

ALLOWED_LANES = {
    "robustness_guardian",
    "advanced_csv",
    "alpha_synthesis",
    "flow_microstructure",
    "apex_council",
}


def utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_input(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("shadow input must be a JSON object")
    return payload, hashlib.sha256(raw).hexdigest()


def build_shadow_request(lane: str, payload: dict[str, object]) -> ModelRequest:
    if lane not in ALLOWED_LANES:
        raise ValueError("unsupported restored-five lane")
    instructions = (
        "You are a read-only ICARUS shadow evidence analyst. "
        "Analyze only the supplied durable JSON evidence. "
        "Do not infer missing facts, do not claim external research, and do not authorize "
        "trading, execution, production activation, or canonical state mutation. "
        "Return a concise structured assessment. execution_authorized=false."
    )
    return ModelRequest(
        lane=lane,
        model=LOCAL_MODEL_ID,
        reasoning_effort="local",
        instructions=instructions,
        input_text=(
            "Assess this immutable liveness/durability evidence for continuity, gaps, "
            "conflicts, and the next safe non-executing research step. "
            "If evidence is fallback-only, say so explicitly. JSON:\n"
            + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        ),
    )


def enforce_evidence_guards(
    source: dict[str, object],
    model_payload: dict[str, object],
) -> dict[str, object]:
    guarded = dict(model_payload)
    gaps = list(model_payload.get("data_gaps", []))
    conflicts = list(model_payload.get("conflicts", []))

    slot_status = source.get("slot_status")
    worker_status = source.get("worker_receipt_status")
    expected_run = source.get("expected_RUN_ID")
    observed_run = source.get("observed_worker_RUN_ID")
    substantive_claim = source.get("substantive_work_claimed")

    if slot_status == "FALLBACK_LIVENESS_ONLY":
        if "FALLBACK_LIVENESS_ONLY" not in gaps:
            gaps.append("FALLBACK_LIVENESS_ONLY")

    if worker_status != "CHATGPT_CANONICAL_RECEIPT_PRESENT":
        marker = f"WORKER_RECEIPT_NOT_VERIFIED:{worker_status}"
        if marker not in gaps:
            gaps.append(marker)

    if substantive_claim is not True:
        if "SUBSTANTIVE_WORK_NOT_PROVEN" not in gaps:
            gaps.append("SUBSTANTIVE_WORK_NOT_PROVEN")

    if (
        isinstance(expected_run, str)
        and isinstance(observed_run, str)
        and observed_run
        and observed_run != expected_run
    ):
        marker = "OBSERVED_WORKER_RUN_ID_DIFFERS_FROM_EXPECTED"
        if marker not in conflicts:
            conflicts.append(marker)

    guarded["net_new_delta"] = "SHADOW_ASSESSMENT_ONLY"
    guarded["data_gaps"] = gaps
    guarded["conflicts"] = conflicts
    guarded["execution_authorized"] = False
    return guarded


def run_shadow(
    lane: str,
    input_path: Path,
    output_path: Path,
    *,
    binary: Path,
    model: Path,
    model_runner: ModelRunner = run_local_model,
    now_fn=lambda: datetime.now(UTC),
) -> Path:
    payload, input_sha = load_input(input_path)
    request = build_shadow_request(lane, payload)
    response = model_runner(
        request,
        binary=binary,
        model=model,
        timeout_seconds=180,
    )
    observed = now_fn()
    if observed.tzinfo is None:
        raise ValueError("shadow clock must be timezone-aware")

    guarded_payload = enforce_evidence_guards(payload, response.payload)

    artifact: dict[str, object] = {
        "schema_version": "restored-five-local-shadow-v1",
        "lane": lane,
        "input_path": input_path.as_posix(),
        "input_sha256": input_sha,
        "observed_at_utc": utc_z(observed),
        "run_origin": "GITHUB_NATIVE_LOCAL_GGUF_SHADOW",
        "inference_backend": "local_gguf",
        "model": LOCAL_MODEL_ID,
        "model_sha256": MODEL_SHA256,
        "llama_cpp_sha256": LLAMA_CPP_SHA256,
        "response_id": response.response_id,
        "response_status": response.status,
        "canonical_state_mutated": False,
        "substantive_research_source": "DURABLE_REPO_EVIDENCE_ONLY",
        "paid_api_call_made": False,
        "api_credential_required": False,
        "execution_authorized": False,
        "payload": guarded_payload,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one restored-five local shadow analysis.")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        path = run_shadow(
            args.lane,
            args.input,
            args.output,
            binary=args.binary,
            model=args.model,
        )
        print(json.dumps({"status": "ok", "output": path.as_posix()}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
