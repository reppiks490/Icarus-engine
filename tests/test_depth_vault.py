import base64
import gzip
import json

import pytest

pytest.importorskip("cryptography")

from tools import depth_vault  # noqa: E402

ENV = {"ICARUS_DATA_ARCHIVE_KEY": base64.b64encode(bytes(range(32))).decode()}


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        f.write(text)


def _cache(tmp_path):
    c = tmp_path / "sweep"
    _write(c / "features/primary/mbp10/nq/2026-10-05.csv.gz", "ts,events\n1,2\n")
    _write(c / "resilience/primary/nq/2026-10-05.csv.gz", "ts,dir\n1,1\n")
    (c / "_retry_raw").mkdir()
    (c / "_retry_raw/primary__2026-10-06.dbn.zst").write_bytes(b"raw vendor bytes")
    return c


def test_round_trip_restores_an_evicted_cache_byte_for_byte(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    before = {p: p.read_bytes() for p in cache.rglob("*.csv.gz")}
    depth_vault.seal({"sweep": cache}, vault, ENV)

    fresh = tmp_path / "evicted"
    out = depth_vault.restore({"sweep": fresh}, vault, ENV)
    assert out == {"restored": 2, "present": 0}
    for p, data in before.items():
        assert (fresh / p.relative_to(cache)).read_bytes() == data


def test_plaintext_never_reaches_the_vault_and_raw_dbn_is_skipped(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    blobs = b"".join(p.read_bytes() for p in (vault / "objects").iterdir())
    assert b"ts,events" not in blobs and b"raw vendor bytes" not in blobs
    manifest = json.loads((vault / "manifest.json").read_text())
    assert not any("_retry_raw" in rel for rel in manifest["caches"]["sweep"])
    assert manifest["key_source"] == "ICARUS_DATA_ARCHIVE_KEY"


def test_resealing_unchanged_cache_writes_nothing(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    assert depth_vault.seal({"sweep": cache}, vault, ENV)["added_objects"] == 2
    manifest = (vault / "manifest.json").read_text()
    assert depth_vault.seal({"sweep": cache}, vault, ENV)["added_objects"] == 0
    assert (vault / "manifest.json").read_text() == manifest


def test_swapped_object_fails_authentication(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    a, b = sorted((vault / "objects").iterdir())
    blob_a = a.read_bytes()
    a.write_bytes(b.read_bytes())
    b.write_bytes(blob_a)
    with pytest.raises(Exception):
        depth_vault.restore({"sweep": tmp_path / "evicted"}, vault, ENV)


def test_present_files_are_never_overwritten(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    out = depth_vault.restore({"sweep": cache}, vault, ENV)
    assert out == {"restored": 0, "present": 2}


def test_wrong_key_source_is_refused(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    with pytest.raises(ValueError, match="sealed with"):
        depth_vault.restore({"sweep": tmp_path / "x"}, vault, {"DATABENTO_API_KEY": "db-other"})


def test_missing_key_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="needs"):
        depth_vault.seal({"sweep": _cache(tmp_path)}, tmp_path / "vault", {})


def test_empty_vault_restores_nothing_without_a_key(tmp_path):
    assert depth_vault.restore({"sweep": tmp_path / "x"}, tmp_path / "vault", {}) == {"restored": 0, "present": 0}
