"""Read-only GitHub-native access for credentialed providers outside the catalog collector.

The module deliberately exposes a small, verified live-access surface rather than
claiming exhaustive endpoint coverage. Raw responses are encrypted locally and
only redacted structural receipts are written to public repository paths.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import zlib
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from icarus_engine.security.credentials import resolve_credential


PROVIDERS = {
    "alphavantage": {
        "base": "https://www.alphavantage.co",
        "canonical": "ALPHAVANTAGE_API_KEY",
        "auth": "query:apikey",
        "path": "/query",
        "params": {"function": "MARKET_STATUS"},
    },
    "finnhub": {
        "base": "https://finnhub.io",
        "canonical": "FINNHUB_API_KEY",
        "auth": "query:token",
        "path": "/api/v1/quote",
        "params": {"symbol": "SPY"},
    },
    "unusual_whales": {
        "base": "https://api.unusualwhales.com",
        "canonical": "UNUSUAL_WHALES_API_KEY",
        "auth": "bearer",
        "path": "/api/market/market-tide",
        "params": {"interval_5m": "true"},
    },
}

_AUTH_FIELD = re.compile(r"(?:api.?key|token|password|secret|authorization)", re.I)
_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z")
_MAX_PAYLOAD = 20_000_000


class ProviderAccessError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ProviderAccessError("REDIRECT_BLOCKED")


def _spec(provider: str) -> dict:
    try:
        return PROVIDERS[provider]
    except KeyError as exc:
        raise KeyError(f"UNKNOWN_PROVIDER:{provider}") from exc


def _credential(provider: str, env: Mapping[str, str]) -> str:
    return (resolve_credential(_spec(provider)["canonical"], env) or "").strip()


def _validate_path(path: str) -> None:
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "://" in path
        or ".." in path
        or "?" in path
        or "#" in path
        or "\\" in path
    ):
        raise ValueError("unsafe provider path")


def build_request(
    provider: str,
    path: str,
    params: Mapping[str, object],
    env: Mapping[str, str] | None = None,
) -> urllib.request.Request:
    """Build an authority-locked GET request with credential injection."""
    spec = _spec(provider)
    _validate_path(path)
    source = os.environ if env is None else env
    key = _credential(provider, source)
    if not key:
        raise ProviderAccessError("MISSING_CREDENTIAL")
    clean: dict[str, object] = {}
    for name, value in params.items():
        if _AUTH_FIELD.search(str(name)):
            raise ValueError("caller may not supply authentication")
        if isinstance(value, (dict, list, tuple, set)):
            raise ValueError("non-scalar provider parameter")
        clean[str(name)] = value

    headers = {
        "Accept": "application/json",
        "User-Agent": "ICARUS-native-provider-access/1",
    }
    auth = spec["auth"]
    if auth == "query:apikey":
        clean["apikey"] = key
    elif auth == "query:token":
        clean["token"] = key
    elif auth == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    else:
        raise ValueError("unsupported provider authentication")

    query = urlencode(clean, doseq=False)
    url = spec["base"] + path + ("?" + query if query else "")
    return urllib.request.Request(url, headers=headers, method="GET")


def fetch_json(
    provider: str,
    path: str,
    params: Mapping[str, object],
    env: Mapping[str, str] | None = None,
):
    request = build_request(provider, path, params, env)
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=20) as response:
        raw = response.read(_MAX_PAYLOAD + 1)
    if len(raw) > _MAX_PAYLOAD:
        raise ProviderAccessError("PAYLOAD_LIMIT_INCOMPLETE")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderAccessError("INVALID_JSON") from exc


def _payload_failure(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    code = payload.get("code") or payload.get("status_code")
    if str(code) in {"401", "403", "402", "429"}:
        return str(code)
    message = " ".join(
        str(payload.get(name, ""))
        for name in ("error", "message", "Error Message", "Information", "Note", "detail")
        if payload.get(name)
    )
    if not message:
        return None
    if re.search(r"rate.?limit|frequency|quota|calls per|requests per", message, re.I):
        return "429"
    if re.search(r"invalid.*(?:api.?key|token)|unauth|authentication", message, re.I):
        return "401"
    if re.search(r"premium|upgrade|subscription|permission|forbidden|access denied", message, re.I):
        return "403"
    if payload.get("error") or payload.get("Error Message"):
        return "PROVIDER_ERROR"
    return None


def _archive_payload(
    root: Path,
    provider: str,
    run_id: str,
    payload: object,
    env: Mapping[str, str],
    provider_key: str,
) -> str:
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF

        encoded = str(env.get("ICARUS_DATA_ARCHIVE_KEY", "")).strip()
        if encoded:
            key = base64.b64decode(encoded, validate=True)
            if len(key) != 32:
                return "NOT_RETAINED_ARCHIVE_KEY_INVALID"
        else:
            key = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"icarus-native-provider-access-v1",
                info=provider.encode("utf-8"),
            ).derive(provider_key.encode("utf-8"))
        nonce = os.urandom(12)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        compressed = zlib.compress(canonical)
        aad = f"{run_id}:{provider}:native-access".encode("utf-8")
        target = root / ".native_provider_archives" / run_id / f"{provider}.enc"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(nonce + AESGCM(key).encrypt(nonce, compressed, aad))
        return "ENCRYPTED_AES256_GCM"
    except (ImportError, ValueError, TypeError):
        return "NOT_RETAINED_ARCHIVE_UNAVAILABLE"


def _safe_status_for_code(code: str) -> str:
    if code == "401":
        return "BLOCKED_AUTHENTICATION"
    if code in {"402", "403"}:
        return "BLOCKED_ENTITLEMENT_OR_PERMISSION"
    if code == "429":
        return "QUOTA_OR_RATE_LIMIT_PAUSED"
    if code == "MISSING_CREDENTIAL":
        return "BLOCKED_MISSING_CREDENTIAL"
    if code in {"REDIRECT_BLOCKED", "PAYLOAD_LIMIT_INCOMPLETE", "INVALID_JSON"}:
        return "BLOCKED_TRANSPORT_OR_PAYLOAD"
    return "PROVIDER_ERROR"


def _write_receipt(root: Path, run_id: str, provider: str, receipt: dict) -> None:
    run_path = root / "automation_intelligence" / "provider_collection_v1" / "native_access" / run_id / f"{provider}.json"
    latest_path = root / "automation_intelligence" / "provider_collection_v1" / "native_access" / "latest" / f"{provider}.json"
    raw = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(raw, encoding="utf-8")
    latest_path.write_text(raw, encoding="utf-8")


def collect_snapshot(
    provider: str,
    root: Path,
    env: Mapping[str, str] | None = None,
    *,
    run_id: str,
    fetch=fetch_json,
) -> dict:
    """Collect one bounded read-only snapshot and persist only a redacted receipt."""
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("unsafe run ID")
    spec = _spec(provider)
    source = os.environ if env is None else env
    key = _credential(provider, source)
    receipt = {
        "schema_version": "icarus-native-provider-access-v1",
        "provider": provider,
        "run_id": run_id,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PENDING",
        "credential_present": bool(key),
        "endpoint": spec["path"],
        "request_count": 0,
        "payload_sha256": None,
        "top_level_keys": [],
        "archive_status": "NOT_ATTEMPTED",
        "raw_payload_public": False,
        "execution_authorized": False,
        "production_decision_authorized": False,
    }
    if not key:
        receipt["status"] = "BLOCKED_MISSING_CREDENTIAL"
        _write_receipt(root, run_id, provider, receipt)
        return receipt

    try:
        receipt["request_count"] = 1
        payload = fetch(provider, spec["path"], dict(spec["params"]), source)
        failure = _payload_failure(payload)
        if failure:
            receipt["status"] = _safe_status_for_code(failure)
        else:
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            receipt["payload_sha256"] = hashlib.sha256(canonical).hexdigest()
            if isinstance(payload, dict):
                receipt["top_level_keys"] = sorted(str(key_name) for key_name in payload.keys())[:64]
            receipt["archive_status"] = _archive_payload(root, provider, run_id, payload, source, key)
            receipt["status"] = "COLLECTED"
    except urllib.error.HTTPError as exc:
        receipt["status"] = _safe_status_for_code(str(exc.code))
    except urllib.error.URLError:
        receipt["status"] = "NETWORK_ERROR"
    except ProviderAccessError as exc:
        receipt["status"] = _safe_status_for_code(exc.code)
    except (ValueError, TypeError, OverflowError):
        receipt["status"] = "PROVIDER_ERROR"

    _write_receipt(root, run_id, provider, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect a bounded GitHub-native provider access snapshot.")
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    receipt = collect_snapshot(args.provider, args.repo_root, os.environ, run_id=args.run_id)
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
