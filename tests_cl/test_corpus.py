from __future__ import annotations

import hashlib
import json

from cl_lab import corpus


def _write(root, bad_hash=False):
    payload = (
        "ts,open,high,low,close,volume\n"
        "2026-10-01T00:00:00Z,1,2,0.5,1.5,10\n"
        "2026-10-01T00:05:00Z,1.5,2.5,1,2,12\n"
    ).encode()
    (root / "nq_5m.csv").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema_version": "icarus-databento-corpus-v1",
        "provider": "databento",
        "dataset": "GLBX.MDP3",
        "roll_rule": "v",
        "minutes": 5,
        "timestamp_semantics": "bar_open_utc",
        "start": "2026-10-01T00:00:00Z",
        "end_exclusive": "2026-10-02T00:00:00Z",
        "generated_at": "2026-10-04T00:00:00Z",
        "assets": {
            "NQ": {
                "status": "OK",
                "file": "nq_5m.csv",
                "rows": 2,
                "sha256": ("0" * 64 if bad_hash else digest),
                "databento_symbol": "NQ.v.0",
                "provider_ticker": "NQ=F",
                "tv_symbol": "CME_MINI:NQ1!",
                "first": "2026-10-01T00:00:00Z",
                "last": "2026-10-01T00:05:00Z"
            }
        }
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_corpus_inspection_verifies_hash_rows_and_schema(tmp_path):
    _write(tmp_path)
    out = corpus.inspect(tmp_path)
    assert out["status"] == "VERIFIED"
    assert out["verified_assets"] == 1
    assert out["assets"]["NQ"]["status"] == "VERIFIED"
    assert out["assets"]["NQ"]["databento_symbol"] == "NQ.v.0"
    assert out["execution_authorized"] is False


def test_corpus_inspection_fails_closed_on_hash_mismatch(tmp_path):
    _write(tmp_path, bad_hash=True)
    out = corpus.inspect(tmp_path)
    assert out["status"] == "BLOCKED"
    assert out["verified_assets"] == 0
    assert out["assets"]["NQ"]["status"] == "BLOCKED"
    assert "sha256 mismatch" in out["assets"]["NQ"]["error"]


def test_corpus_inspection_is_unavailable_without_configuration(monkeypatch):
    monkeypatch.delenv(corpus.ENV, raising=False)
    out = corpus.inspect()
    assert out["status"] == "UNAVAILABLE"
    assert out["assets"] == {}
