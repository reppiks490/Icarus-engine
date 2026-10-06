import gzip
import json
from pathlib import Path

from cl_lab.data_fabric.contracts import Observation, raw_sha256, redact_text
from cl_lab.data_fabric.storage import partition_for, write_bronze, write_manifest, write_silver


def test_observation_contract_and_stable_id():
    a = Observation.build(
        provider="intrinio", dataset="prices", endpoint="/securities/{identifier}/prices", entity="AAPL",
        event_time="2026-10-01T16:00:00-04:00", publication_time=None,
        availability_time="2026-10-01T20:00:01Z", retrieval_time="2026-10-02T00:00:00Z",
        revision="v1", latency_class="eod", quality_state="raw", license_class="provider-restricted",
        payload={"close": 250.5}, raw_bytes=b'{"close":250.5}',
    )
    b = Observation.build(
        provider="intrinio", dataset="prices", endpoint="/securities/{identifier}/prices", entity="AAPL",
        event_time="2026-10-01T20:00:00Z", publication_time=None,
        availability_time="2026-10-01T20:00:01Z", retrieval_time="2026-10-03T00:00:00Z",
        revision="v1", latency_class="eod", quality_state="raw", license_class="provider-restricted",
        payload={"close": 250.5}, raw_bytes=b'{"close":250.5}',
    )
    d = a.as_dict()
    required = {
        "provider", "dataset", "endpoint", "entity", "event_time", "publication_time", "availability_time",
        "retrieval_time", "revision", "latency_class", "quality_state", "source_record_id",
        "raw_content_hash", "license_class", "payload",
    }
    assert required == set(d)
    assert d["event_time"] == "2026-10-01T20:00:00Z"
    assert a.source_record_id == b.source_record_id
    assert a.raw_content_hash == raw_sha256(b'{"close":250.5}')


def test_redaction_never_echoes_secret():
    text = "request failed Authorization Bearer abc123 and api_key=abc123"
    redacted = redact_text(text, ["abc123"])
    assert "abc123" not in redacted
    assert "[REDACTED]" in redacted


def test_partition_and_atomic_storage(tmp_path):
    assert partition_for("2026-10-01T20:00:00Z") == "date=2026-10-01"
    bronze = write_bronze(tmp_path, "intrinio", "prices", b"raw-payload", "2026-10-01T20:00:00Z")
    p = Path(bronze["path"])
    assert p.exists()
    assert gzip.decompress(p.read_bytes()) == b"raw-payload"
    assert bronze["sha256"] == raw_sha256(b"raw-payload")
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, {"z": 1, "a": 2})
    assert json.loads(manifest.read_text()) == {"a": 2, "z": 1}
    assert not list(tmp_path.rglob("*.tmp"))


def test_silver_has_deterministic_portable_fallback(tmp_path, monkeypatch):
    rows = [{
        "provider": "intrinio", "dataset": "prices", "endpoint": "x", "entity": "AAPL",
        "event_time": "2026-10-01T20:00:00Z", "publication_time": None,
        "availability_time": "2026-10-01T20:00:01Z", "retrieval_time": "2026-10-01T20:00:02Z",
        "revision": None, "latency_class": "eod", "quality_state": "raw", "source_record_id": "1",
        "raw_content_hash": "a" * 64, "license_class": "provider-restricted", "payload": {"close": 1},
    }]
    monkeypatch.setenv("ICARUS_DATA_FABRIC_FORCE_JSONL", "1")
    meta = write_silver(tmp_path, "intrinio", "prices", rows, "2026-10-01T20:00:00Z")
    assert meta["format"] == "jsonl.gz"
    data = gzip.decompress(Path(meta["path"]).read_bytes()).decode()
    assert json.loads(data.strip())["entity"] == "AAPL"
