from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Mapping

DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"
WIF_TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
DEFAULT_TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class AIPlaneError(RuntimeError):
    pass


class ConfigurationError(AIPlaneError):
    pass


class TransportError(AIPlaneError):
    pass


class AuthenticationError(TransportError):
    pass


class OutputValidationError(AIPlaneError):
    pass


@dataclass(frozen=True)
class ModelRequest:
    lane: str
    model: str
    reasoning_effort: str
    instructions: str
    input_text: str


@dataclass(frozen=True)
class ModelResponse:
    response_id: str
    status: str
    payload: dict[str, object]


Transport = Callable[[str, dict[str, str], bytes, int], tuple[int, bytes]]
OidcTransport = Callable[[str, dict[str, str], int], tuple[int, bytes]]


def _lane_schema(lane: str) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "lane": {"type": "string", "enum": [lane]},
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


def build_request_payload(request: ModelRequest) -> dict[str, object]:
    if not request.lane:
        raise ConfigurationError("lane is required")
    if not request.model:
        raise ConfigurationError("model is required")
    if request.reasoning_effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
        raise ConfigurationError("unsupported reasoning effort")
    return {
        "model": request.model,
        "instructions": request.instructions,
        "input": request.input_text,
        "reasoning": {"effort": request.reasoning_effort},
        "text": {
            "format": {
                "type": "json_schema",
                "name": f"{request.lane}_automation_output",
                "strict": True,
                "schema": _lane_schema(request.lane),
            }
        },
        "store": False,
    }


def validate_lane_output(payload: object, lane: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise OutputValidationError("lane output must be an object")
    required = {
        "lane",
        "summary",
        "net_new_delta",
        "data_gaps",
        "conflicts",
        "execution_authorized",
    }
    if set(payload) != required:
        raise OutputValidationError("lane output keys mismatch")
    if payload.get("lane") != lane:
        raise OutputValidationError("lane mismatch")
    if not isinstance(payload.get("summary"), str):
        raise OutputValidationError("summary must be a string")
    if not isinstance(payload.get("net_new_delta"), str):
        raise OutputValidationError("net_new_delta must be a string")
    for key in ("data_gaps", "conflicts"):
        value = payload.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise OutputValidationError(f"{key} must be a string array")
    if payload.get("execution_authorized") is not False:
        raise OutputValidationError("execution_authorized must be false")
    return dict(payload)


def _default_transport(
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout: int,
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except Exception as exc:
        raise TransportError("network transport failure") from None


def _extract_output_text(response: dict[str, object]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct:
        return direct

    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        return text
    raise OutputValidationError("response did not contain output_text")



def _default_oidc_transport(
    url: str,
    headers: dict[str, str],
    timeout: int,
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except Exception:
        raise AuthenticationError("GitHub OIDC token request failed") from None


def resolve_openai_bearer_token(
    env: Mapping[str, str],
    *,
    oidc_transport: OidcTransport | None = None,
    exchange_transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> str:
    api_key = env.get("OPENAI_API_KEY", "").strip()
    if api_key:
        return api_key

    identity_provider_id = env.get("OPENAI_IDENTITY_PROVIDER_ID", "").strip()
    service_account_id = env.get("OPENAI_SERVICE_ACCOUNT_ID", "").strip()
    audience = env.get("OPENAI_WIF_AUDIENCE", "").strip()
    wif_values = (identity_provider_id, service_account_id, audience)
    if not any(wif_values):
        raise ConfigurationError("OpenAI authentication is not configured")
    if not all(wif_values):
        raise ConfigurationError("OpenAI workload identity configuration is incomplete")

    request_url = env.get("ACTIONS_ID_TOKEN_REQUEST_URL", "").strip()
    request_token = env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "").strip()
    if not request_url or not request_token:
        raise ConfigurationError("GitHub workload identity environment is unavailable")

    parsed = urllib.parse.urlsplit(request_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["audience"] = audience
    oidc_url = urllib.parse.urlunsplit(
        parsed._replace(query=urllib.parse.urlencode(query))
    )

    oidc_send = oidc_transport or _default_oidc_transport
    try:
        oidc_status, oidc_body = oidc_send(
            oidc_url,
            {"Authorization": f"bearer {request_token}"},
            timeout_seconds,
        )
    except AuthenticationError:
        raise
    except Exception:
        raise AuthenticationError("GitHub OIDC token request failed") from None
    if oidc_status < 200 or oidc_status >= 300:
        raise AuthenticationError(f"GitHub OIDC token request failed: HTTP {oidc_status}")

    try:
        oidc_payload = json.loads(oidc_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AuthenticationError("GitHub OIDC token response was malformed") from None
    subject_token = oidc_payload.get("value") if isinstance(oidc_payload, dict) else None
    if not isinstance(subject_token, str) or not subject_token:
        raise AuthenticationError("GitHub OIDC token response did not include a token")

    exchange_body = json.dumps(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "subject_token": subject_token,
            "identity_provider_id": identity_provider_id,
            "service_account_id": service_account_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    exchange_send = exchange_transport or _default_transport
    try:
        exchange_status, exchange_response = exchange_send(
            WIF_TOKEN_ENDPOINT,
            {"Content-Type": "application/json"},
            exchange_body,
            timeout_seconds,
        )
    except Exception:
        raise AuthenticationError("OpenAI workload identity exchange failed") from None
    if exchange_status < 200 or exchange_status >= 300:
        raise AuthenticationError(
            f"OpenAI workload identity exchange failed: HTTP {exchange_status}"
        )

    try:
        exchange_payload = json.loads(exchange_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AuthenticationError("OpenAI workload identity response was malformed") from None
    access_token = (
        exchange_payload.get("access_token")
        if isinstance(exchange_payload, dict)
        else None
    )
    if not isinstance(access_token, str) or not access_token:
        raise AuthenticationError("OpenAI workload identity response did not include an access token")
    return access_token


def call_responses_api(
    request: ModelRequest,
    api_key: str,
    *,
    transport: Transport | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ModelResponse:
    if not isinstance(api_key, str) or not api_key.strip():
        raise ConfigurationError("OPENAI_API_KEY is missing")
    if timeout_seconds <= 0:
        raise ConfigurationError("timeout_seconds must be positive")

    payload = build_request_payload(request)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    send = transport or _default_transport

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status_code, response_body = send(endpoint, headers, body, timeout_seconds)
        except TransportError:
            if attempt == MAX_ATTEMPTS:
                raise
            sleep_fn(float(attempt))
            continue
        except Exception:
            if attempt == MAX_ATTEMPTS:
                raise TransportError("network transport failure") from None
            sleep_fn(float(attempt))
            continue

        if status_code in {401, 403}:
            raise AuthenticationError(f"OpenAI authentication failed: HTTP {status_code}")
        if status_code in RETRYABLE_STATUS:
            if attempt == MAX_ATTEMPTS:
                raise TransportError(f"OpenAI request failed after retries: HTTP {status_code}")
            sleep_fn(float(attempt))
            continue
        if status_code < 200 or status_code >= 300:
            raise TransportError(f"OpenAI request failed: HTTP {status_code}")

        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TransportError("OpenAI response contained malformed JSON") from None
        if not isinstance(decoded, dict):
            raise TransportError("OpenAI response must be a JSON object")

        response_id = decoded.get("id")
        status = decoded.get("status")
        if not isinstance(response_id, str) or not response_id:
            raise OutputValidationError("response id missing")
        if status != "completed":
            raise OutputValidationError(f"response status is not completed: {status}")

        text = _extract_output_text(decoded)
        try:
            lane_payload = json.loads(text)
        except json.JSONDecodeError:
            raise OutputValidationError("output_text was not valid JSON") from None
        validated = validate_lane_output(lane_payload, request.lane)
        return ModelResponse(
            response_id=response_id,
            status=status,
            payload=validated,
        )

    raise TransportError("OpenAI request exhausted retry loop")
