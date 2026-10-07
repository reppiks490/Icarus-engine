from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import tempfile
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


def lane_json_schema(lane: str | None = None) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "lane": {"type": "string", **({"enum": [lane]} if lane is not None else {})},
            "summary": {"type": "string"},
            "net_new_delta": {"type": "string"},
            "data_gaps": {"type": "array", "items": {"type": "string"}},
            "conflicts": {"type": "array", "items": {"type": "string"}},
            "execution_authorized": {"type": "boolean", "enum": [False]},
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
    *,
    output_file: Path | None = None,
) -> list[str]:
    is_completion = binary.name == "llama-completion"
    command = [
        str(binary),
        "-m",
        str(model),
        "-sys",
        request.instructions,
        "-p",
        request.input_text,
        "-st",
        "--no-display-prompt",
        "--jinja",
        "--reasoning",
        "off",
        "--json-schema",
        json.dumps(lane_json_schema(request.lane), sort_keys=True, separators=(",", ":")),
        "-t",
        "4",
        "-c",
        "4096",
        "-n",
        "768",
        "--temp",
        "0",
        "-co",
        "off",
    ]
    if not is_completion:
        command.extend([
            "--simple-io",
            "--no-show-timings",
        ])
    if output_file is not None and not is_completion:
        command.extend(["-o", str(output_file)])
    return command


def wrap_terminal_command(
    command: list[str],
    *,
    script_binary: str | None = None,
) -> list[str]:
    # llama-completion is designed for redirected one-and-done automation.
    # llama-cli still needs a pseudo-terminal on affected Linux builds.
    if Path(command[0]).name == "llama-completion":
        return command
    binary = script_binary if script_binary is not None else shutil.which("script")
    if not binary:
        return command
    return [
        binary,
        "-q",
        "-e",
        "-c",
        shlex.join(command),
        "/dev/null",
    ]


def _default_executor(command: list[str], timeout_seconds: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            wrap_terminal_command(command),
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


def normalize_terminal_text(text: str) -> str:
    # Strip CSI/OSC terminal controls and normalize CR/backspace artifacts
    # before structured parsing. Do not attempt to interpret model reasoning.
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    while "\b" in text:
        text = re.sub(r"[^\n]\b", "", text)
        text = text.replace("\b", "")
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)


def safe_generation_preview(text: str, limit: int = 320) -> str:
    cleaned = normalize_terminal_text(text)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    open_think = re.search(r"<think>", cleaned, flags=re.IGNORECASE)
    if open_think is not None:
        cleaned = cleaned[:open_think.start()]
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]


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

    with tempfile.TemporaryDirectory(prefix="icarus-local-model-") as temp_dir:
        output_file = Path(temp_dir) / "generation.txt"
        command = build_local_model_command(
            binary,
            model,
            request,
            output_file=output_file,
        )
        exit_code, stdout, stderr = executor(command, timeout_seconds)
        if exit_code != 0:
            stdout_preview = safe_generation_preview(stdout)
            stderr_preview = safe_generation_preview(stderr)
            raise TransportError(
                f"local model runtime failed with exit code {exit_code}; "
                f"safe_stdout_preview={stdout_preview!r} "
                f"safe_stderr_preview={stderr_preview!r}"
            )

        generated = ""
        if output_file.is_file():
            generated = output_file.read_text(encoding="utf-8", errors="replace")
        normalized_generated = normalize_terminal_text(generated)
        normalized_stdout = normalize_terminal_text(stdout)
        try:
            payload = extract_json_object(normalized_generated)
            response_text = normalized_generated
        except TransportError:
            try:
                payload = extract_json_object(normalized_stdout)
                response_text = normalized_stdout
            except TransportError:
                generated_preview = safe_generation_preview(generated)
                stdout_preview = safe_generation_preview(stdout)
                raise TransportError(
                    "local model did not return structured JSON; "
                    f"generated_len={len(generated)} stdout_len={len(stdout)} "
                    f"safe_generated_preview={generated_preview!r} "
                    f"safe_stdout_preview={stdout_preview!r}"
                ) from None

    validated = validate_lane_output(payload, request.lane)
    response_hash = hashlib.sha256(response_text.encode("utf-8")).hexdigest()[:24]
    return ModelResponse(
        response_id=f"local-{response_hash}",
        status="completed",
        payload=validated,
    )
