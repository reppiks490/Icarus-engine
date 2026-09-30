from __future__ import annotations

import argparse
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
NowFn = Callable[[], datetime]


def _utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_canary_request() -> ModelRequest:
    return ModelRequest(
        lane="aion",
        model=LOCAL_MODEL_ID,
        reasoning_effort="local",
        instructions=(
            "You are an isolated local-model runtime canary. "
            "Return exactly the requested structured status object. "
            "Never authorize trading or execution. execution_authorized=false."
        ),
        input_text=(
            "Report that this local inference canary executed. "
            "Set lane to aion, net_new_delta to CANARY_OK, "
            "data_gaps and conflicts to empty arrays, and execution_authorized to false."
        ),
    )


def run_canary(
    binary: Path,
    model: Path,
    output: Path,
    *,
    model_runner: ModelRunner = run_local_model,
    now_fn: NowFn | None = None,
) -> Path:
    clock = now_fn or (lambda: datetime.now(timezone.utc))
    request = build_canary_request()
    response = model_runner(
        request,
        binary=binary,
        model=model,
        timeout_seconds=180,
    )
    observed = clock()
    if observed.tzinfo is None:
        raise ValueError("canary clock must be timezone-aware")

    payload: dict[str, object] = {
        "schema_version": "omega-stack-local-model-canary-v1",
        "inference_backend": "local_gguf",
        "model": LOCAL_MODEL_ID,
        "model_sha256": MODEL_SHA256,
        "llama_cpp_sha256": LLAMA_CPP_SHA256,
        "response_id": response.response_id,
        "response_status": response.status,
        "observed_at_utc": _utc_z(observed),
        "paid_api_call_made": False,
        "api_credential_required": False,
        "execution_authorized": False,
        "payload": response.payload,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one zero-cost local GGUF canary.")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        path = run_canary(args.binary, args.model, args.output)
        print(json.dumps({"status": "ok", "output": path.as_posix()}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
