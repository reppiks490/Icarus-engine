from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


class PersistenceError(ValueError):
    """Raised when persisted agent-run artifacts fail closed consistency checks."""


def _mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PersistenceError(f"{name} must be a mapping")
    return value


def _require_false(name: str, artifact: Mapping[str, Any]) -> None:
    if artifact.get("execution_authorized") is not False:
        raise PersistenceError(f"{name}.execution_authorized must be false")


def canonical_run_core_sha256(run_core: Mapping[str, Any]) -> str:
    core = _mapping("RUN_CORE", run_core)
    try:
        payload = json.dumps(
            core,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PersistenceError(f"RUN_CORE is not canonicalizable JSON: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def validate_finalized_run(
    *,
    history: Mapping[str, Any],
    latest: Mapping[str, Any],
    state: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
    finalization: Mapping[str, Any],
    actual_history_blob_sha: str,
    actual_latest_blob_sha: str,
) -> dict[str, Any]:
    """Validate the complete agent-fabric persistence chain.

    The validator intentionally requires a finalization receipt that binds the
    actual immutable-history and current-latest blob identities.  Prose claims
    or scheduler timestamps are never accepted as persistence proof.
    """

    h = _mapping("history", history)
    l = _mapping("latest", latest)
    s = _mapping("state", state)
    b = _mapping("heartbeat", heartbeat)
    r = _mapping("finalization", finalization)

    if not actual_history_blob_sha or not actual_latest_blob_sha:
        raise PersistenceError("actual history/latest blob SHAs are required")

    h_core = _mapping("history.RUN_CORE", h.get("RUN_CORE"))
    l_core = _mapping("latest.RUN_CORE", l.get("RUN_CORE"))
    expected_hash = canonical_run_core_sha256(h_core)

    if canonical_run_core_sha256(l_core) != expected_hash:
        raise PersistenceError("history/latest RUN_CORE content mismatch")
    if h.get("RUN_CORE_SHA256") != expected_hash:
        raise PersistenceError("history RUN_CORE_SHA256 mismatch")
    if l.get("RUN_CORE_SHA256") != expected_hash:
        raise PersistenceError("latest RUN_CORE_SHA256 mismatch")

    run_id = h_core.get("RUN_ID")
    agent = h_core.get("agent")
    protocol = h_core.get("persistence_protocol_version")
    if not isinstance(run_id, str) or not run_id:
        raise PersistenceError("RUN_CORE.RUN_ID must be non-empty")
    if not isinstance(agent, str) or not agent:
        raise PersistenceError("RUN_CORE.agent must be non-empty")
    if protocol != "agent-fabric-persistence-v3":
        raise PersistenceError("unsupported agent persistence protocol")

    if h.get("RUN_STATUS") != "HISTORY_VERIFIED":
        raise PersistenceError("immutable history must be HISTORY_VERIFIED")
    if l.get("RUN_STATUS") != "RUN_PERSISTED":
        raise PersistenceError("latest must be RUN_PERSISTED")
    if s.get("last_successful_run_id") != run_id:
        raise PersistenceError("state last_successful_run_id mismatch")
    if b.get("RUN_ID") != run_id:
        raise PersistenceError("heartbeat RUN_ID mismatch")
    if b.get("RUN_STATUS") not in {"RUN_PERSISTED", "FINALIZED"}:
        raise PersistenceError("heartbeat is not finalized")
    if r.get("RUN_ID") != run_id:
        raise PersistenceError("finalization RUN_ID mismatch")
    if r.get("RUN_STATUS") != "FINALIZATION_VERIFIED":
        raise PersistenceError("finalization receipt is not verified")
    if r.get("RUN_CORE_SHA256") != expected_hash:
        raise PersistenceError("finalization RUN_CORE_SHA256 mismatch")

    if l.get("history_blob_sha") != actual_history_blob_sha:
        raise PersistenceError("latest does not bind actual history blob")
    if r.get("history_blob_sha") != actual_history_blob_sha:
        raise PersistenceError("receipt history blob mismatch")
    if r.get("latest_blob_sha") != actual_latest_blob_sha:
        raise PersistenceError("receipt latest blob mismatch")

    _require_false("RUN_CORE", h_core)
    for name, artifact in (
        ("history", h),
        ("latest", l),
        ("state", s),
        ("heartbeat", b),
        ("finalization", r),
    ):
        _require_false(name, artifact)

    return {
        "status": "FINALIZATION_VERIFIED",
        "RUN_ID": run_id,
        "agent": agent,
        "RUN_CORE_SHA256": expected_hash,
        "history_blob_sha": actual_history_blob_sha,
        "latest_blob_sha": actual_latest_blob_sha,
        "execution_authorized": False,
    }
