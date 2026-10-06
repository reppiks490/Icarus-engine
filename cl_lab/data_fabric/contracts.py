from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable


def raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    dt = dt.astimezone(timezone.utc)
    out = dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return out.replace(".000000Z", "Z")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def redact_text(text: Any, secrets: Iterable[str] = ()) -> str:
    out = str(text)
    for secret in secrets:
        if secret:
            out = out.replace(str(secret), "[REDACTED]")
    return out


@dataclass(frozen=True)
class Observation:
    provider: str
    dataset: str
    endpoint: str
    entity: str | None
    event_time: str | None
    publication_time: str | None
    availability_time: str | None
    retrieval_time: str
    revision: str | None
    latency_class: str
    quality_state: str
    source_record_id: str
    raw_content_hash: str
    license_class: str
    payload: Any

    @classmethod
    def build(
        cls,
        *,
        provider: str,
        dataset: str,
        endpoint: str,
        entity: str | None,
        event_time: Any,
        publication_time: Any,
        availability_time: Any,
        retrieval_time: Any,
        revision: str | None,
        latency_class: str,
        quality_state: str,
        license_class: str,
        payload: Any,
        raw_bytes: bytes | None = None,
        source_record_id: str | None = None,
    ) -> "Observation":
        provider = str(provider).strip().lower()
        dataset = str(dataset).strip()
        endpoint = str(endpoint).strip()
        if not provider or not dataset or not endpoint:
            raise ValueError("provider, dataset and endpoint are required")
        ev = _utc_iso(event_time)
        pub = _utc_iso(publication_time)
        avail = _utc_iso(availability_time)
        ret = _utc_iso(retrieval_time)
        if ret is None:
            raise ValueError("retrieval_time is required")
        raw = raw_bytes if raw_bytes is not None else _canonical_json(payload)
        content_hash = raw_sha256(raw)
        if source_record_id is None:
            stable = {
                "provider": provider,
                "dataset": dataset,
                "endpoint": endpoint,
                "entity": entity,
                "event_time": ev,
                "revision": revision,
                "payload": payload,
            }
            source_record_id = hashlib.sha256(_canonical_json(stable)).hexdigest()
        return cls(
            provider=provider,
            dataset=dataset,
            endpoint=endpoint,
            entity=None if entity is None else str(entity),
            event_time=ev,
            publication_time=pub,
            availability_time=avail,
            retrieval_time=ret,
            revision=None if revision is None else str(revision),
            latency_class=str(latency_class),
            quality_state=str(quality_state),
            source_record_id=str(source_record_id),
            raw_content_hash=content_hash,
            license_class=str(license_class),
            payload=payload,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
