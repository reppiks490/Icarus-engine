from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Callable

from tools.github_native_ai_openai import (
    ModelRequest,
    ModelResponse,
    TransportError,
    validate_lane_output,
)

LLAMA_CPP_URL = (
    "https://github.com/ggml-org/llama.cpp/releases/download/"
    "b10978/llama-b10978-bin-ubuntu-x64.tar.gz"
)
LLAMA_CPP_SHA256 = "98020bb5a2a9e0284110e5c110158e18dca984a547d5afde1631fef0f03dd826"
MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/"
    "90862c4b9d2787eaed51d12237eafdfe7c5f6077/Qwen3-1.7B-Q8_0.gguf"
)
MODEL_SHA256 = "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a"
MODEL_SIZE_BYTES = 1_834_426_016
LOCAL_MODEL_ID = "Qwen/Qwen3-1.7B-GGUF@90862c4:Q8_0"

Executor = Callable[[list[str], int], tuple[int, str, str]]


def lane_json_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "lane": {"type": "string"},
            "summary": {"type": "string"},
            "net_new_delta": {"type": "string"},
            "data_gaps": {"type": "array", "items": {"type": "string"}},
            "conflicts": {"type": "array", "items": {"type": "string"}},
            "execution_authorized": {"type": "boolean"},
        },
        "required": [
            "lane",
            "summary",
            "net_new_delta",
            "data_gaps",
            "conflicts",
            "execution_authorized",
        ],
        "additionalProperties": False,
    }


def build_local_model_command(
    binary: Path,
    model: Path,
    request: ModelRequest,
) -> list[str]:
    return [
        str(binary),
        "-m",
        str(model),
        "-sys",
        request.instructions,
        "-p",
        request.input_text,
        "-st",
        "--simple-io",
        "--no-display-prompt",
        "--no-show-timings",
        "--reasoning-budget",
        "0",
        "--json-schema",
        json.dumps(lane_json_schema(), sort_keys=True, separators=(",", ":")),
        "-t",
        "4",
        "-c",
        "4096",
        "-n",
        "384",
        "--temp",
        "0",
        "-co",
        "off",
    ]


def _default_executor(command: list[str], timeout_seconds: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise TransportError("local model runtime timed out") from None
    except OSError:
        raise TransportError("local model runtime could not start") from None
    return result.returncode, result.stdout, result.stderr


def extract_json_object(text: str) -> dict[str, object]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise TransportError("local model did not return structured JSON")


def run_local_model(
    request: ModelRequest,
    *,
    binary: Path,
    model: Path,
    executor: Executor = _default_executor,
    timeout_seconds: int = 180,
) -> ModelResponse:
    if not binary.is_file():
        raise TransportError("local model runtime is missing")
    if not model.is_file():
        raise TransportError("local model file is missing")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    command = build_local_model_command(binary, model, request)
    exit_code, stdout, _stderr = executor(command, timeout_seconds)
    if exit_code != 0:
        raise TransportError(f"local model runtime failed with exit code {exit_code}")

    payload = extract_json_object(stdout)
    validated = validate_lane_output(payload, request.lane)
    response_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()[:24]
    return ModelResponse(
        response_id=f"local-{response_hash}",
        status="completed",
        payload=validated,
    )
