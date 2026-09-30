from __future__ import annotations

import json

import pytest

from tools.github_native_ai_openai import (
    AuthenticationError,
    ConfigurationError,
    ModelRequest,
    OutputValidationError,
    TransportError,
    build_request_payload,
    call_responses_api,
    resolve_openai_bearer_token,
    validate_lane_output,
)


def _request(lane: str = "aion") -> ModelRequest:
    return ModelRequest(
        lane=lane,
        model="gpt-5.6-sol",
        reasoning_effort="high",
        instructions="Return only the requested structured output.",
        input_text="Run the lane.",
    )


def _valid_output(lane: str = "aion") -> dict[str, object]:
    return {
        "lane": lane,
        "summary": "No material change.",
        "net_new_delta": "NONE",
        "data_gaps": [],
        "conflicts": [],
        "execution_authorized": False,
    }


def _response_body(lane: str = "aion") -> bytes:
    payload = {
        "id": "resp_test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(_valid_output(lane), separators=(",", ":")),
                    }
                ],
            }
        ],
    }
    return json.dumps(payload).encode()


def test_missing_api_key_fails_before_transport() -> None:
    called = False

    def transport(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("transport must not run")

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        call_responses_api(_request(), "", transport=transport)

    assert called is False


def test_request_payload_uses_responses_structured_output_contract() -> None:
    payload = build_request_payload(_request())

    assert payload["model"] == "gpt-5.6-sol"
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["store"] is False
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"]["additionalProperties"] is False
    assert payload["text"]["format"]["schema"]["properties"]["lane"]["enum"] == ["aion"]
    assert payload["text"]["format"]["schema"]["properties"]["execution_authorized"]["enum"] == [False]


def test_authorization_header_is_sent_but_secret_is_not_in_result_or_errors() -> None:
    secret = "sk-secret-value"

    def transport(url, headers, body, timeout):
        assert headers["Authorization"] == f"Bearer {secret}"
        assert secret.encode() not in body
        return 200, _response_body()

    result = call_responses_api(_request(), secret, transport=transport)

    assert result.response_id == "resp_test"
    assert result.status == "completed"
    assert secret not in repr(result)


def test_429_is_retried_with_a_strict_bound() -> None:
    calls = 0

    def transport(url, headers, body, timeout):
        nonlocal calls
        calls += 1
        if calls < 3:
            return 429, b'{"error":{"message":"rate limited"}}'
        return 200, _response_body()

    result = call_responses_api(_request(), "sk-test", transport=transport, sleep_fn=lambda _: None)

    assert result.status == "completed"
    assert calls == 3


def test_429_exhaustion_fails_after_three_attempts() -> None:
    calls = 0

    def transport(url, headers, body, timeout):
        nonlocal calls
        calls += 1
        return 429, b'{"error":{"message":"rate limited"}}'

    with pytest.raises(TransportError, match="HTTP 429"):
        call_responses_api(_request(), "sk-test", transport=transport, sleep_fn=lambda _: None)

    assert calls == 3


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failures_do_not_retry(status: int) -> None:
    calls = 0

    def transport(url, headers, body, timeout):
        nonlocal calls
        calls += 1
        return status, b'{"error":{"message":"credential rejected"}}'

    with pytest.raises(AuthenticationError, match=f"HTTP {status}"):
        call_responses_api(_request(), "sk-private", transport=transport)

    assert calls == 1


def test_timeout_is_sanitized() -> None:
    def transport(url, headers, body, timeout):
        raise TimeoutError("network timed out while using sk-never-log-me")

    with pytest.raises(TransportError) as exc:
        call_responses_api(_request(), "sk-never-log-me", transport=transport, sleep_fn=lambda _: None)

    assert "sk-never-log-me" not in str(exc.value)


def test_malformed_api_json_is_rejected() -> None:
    def transport(url, headers, body, timeout):
        return 200, b"not-json"

    with pytest.raises(TransportError, match="malformed JSON"):
        call_responses_api(_request(), "sk-test", transport=transport)


def test_missing_output_text_is_rejected() -> None:
    def transport(url, headers, body, timeout):
        return 200, b'{"id":"resp_x","status":"completed","output":[]}'

    with pytest.raises(OutputValidationError, match="output_text"):
        call_responses_api(_request(), "sk-test", transport=transport)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"lane": "wrong", "summary": "x", "net_new_delta": "x", "data_gaps": [], "conflicts": [], "execution_authorized": False},
        {"lane": "aion", "summary": 3, "net_new_delta": "x", "data_gaps": [], "conflicts": [], "execution_authorized": False},
        {"lane": "aion", "summary": "x", "net_new_delta": "x", "data_gaps": "bad", "conflicts": [], "execution_authorized": False},
        {"lane": "aion", "summary": "x", "net_new_delta": "x", "data_gaps": [], "conflicts": [], "execution_authorized": True},
    ],
)
def test_lane_output_validation_fails_closed(payload: object) -> None:
    with pytest.raises(OutputValidationError):
        validate_lane_output(payload, "aion")


def test_lane_output_validation_accepts_exact_contract() -> None:
    payload = _valid_output()
    assert validate_lane_output(payload, "aion") == payload


def test_api_key_is_preferred_over_workload_identity() -> None:
    env = {
        "OPENAI_API_KEY": "sk-primary",
        "OPENAI_IDENTITY_PROVIDER_ID": "idp_unused",
        "OPENAI_SERVICE_ACCOUNT_ID": "svc_unused",
        "OPENAI_WIF_AUDIENCE": "https://api.openai.com/v1",
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("WIF transport must not run when API key exists")

    assert resolve_openai_bearer_token(
        env,
        oidc_transport=forbidden,
        exchange_transport=forbidden,
    ) == "sk-primary"


def test_missing_all_openai_auth_fails_closed() -> None:
    with pytest.raises(ConfigurationError, match="authentication"):
        resolve_openai_bearer_token({})


def test_github_oidc_wif_exchanges_for_short_lived_openai_token() -> None:
    env = {
        "OPENAI_IDENTITY_PROVIDER_ID": "idp_123",
        "OPENAI_SERVICE_ACCOUNT_ID": "svc_456",
        "OPENAI_WIF_AUDIENCE": "https://api.openai.com/v1",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.actions.githubusercontent.com/oidc?job=1",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "github-request-secret",
    }
    seen = {}

    def oidc_transport(url, headers, timeout):
        seen["oidc_url"] = url
        assert headers["Authorization"] == "bearer github-request-secret"
        return 200, b'{"value":"github-subject-jwt"}'

    def exchange_transport(url, headers, body, timeout):
        seen["exchange_url"] = url
        assert headers["Content-Type"] == "application/json"
        payload = json.loads(body)
        assert payload == {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "subject_token": "github-subject-jwt",
            "identity_provider_id": "idp_123",
            "service_account_id": "svc_456",
        }
        return 200, b'{"access_token":"openai-short-lived-token","token_type":"Bearer","expires_in":3600}'

    token = resolve_openai_bearer_token(
        env,
        oidc_transport=oidc_transport,
        exchange_transport=exchange_transport,
    )

    assert token == "openai-short-lived-token"
    assert "audience=https%3A%2F%2Fapi.openai.com%2Fv1" in seen["oidc_url"]
    assert seen["exchange_url"] == "https://auth.openai.com/oauth/token"


def test_incomplete_wif_configuration_fails_without_oidc_request() -> None:
    called = False

    def oidc_transport(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("OIDC request must not run")

    with pytest.raises(ConfigurationError, match="workload identity"):
        resolve_openai_bearer_token(
            {"OPENAI_IDENTITY_PROVIDER_ID": "idp_only"},
            oidc_transport=oidc_transport,
        )
    assert called is False


def test_wif_exchange_errors_are_sanitized() -> None:
    env = {
        "OPENAI_IDENTITY_PROVIDER_ID": "idp_123",
        "OPENAI_SERVICE_ACCOUNT_ID": "svc_456",
        "OPENAI_WIF_AUDIENCE": "https://api.openai.com/v1",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.actions.githubusercontent.com/oidc",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "github-request-secret",
    }

    def oidc_transport(url, headers, timeout):
        return 200, b'{"value":"github-subject-jwt"}'

    def exchange_transport(url, headers, body, timeout):
        raise TimeoutError("failed with github-subject-jwt and github-request-secret")

    with pytest.raises(AuthenticationError) as excinfo:
        resolve_openai_bearer_token(
            env,
            oidc_transport=oidc_transport,
            exchange_transport=exchange_transport,
        )

    message = str(excinfo.value)
    assert "github-subject-jwt" not in message
    assert "github-request-secret" not in message
