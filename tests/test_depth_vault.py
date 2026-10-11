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


def _sources(vault, **caches):
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "sources.json").write_text(json.dumps({"caches": caches}))


def _ledger(root, name, account, entries):
    path = root / "ledgers" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"account": account, "entries": entries}))
    return path.parent


def test_plain_csv_seals_only_when_asked(tmp_path):
    panel, vault = tmp_path / "panel", tmp_path / "vault"
    panel.mkdir()
    (panel / "SPY_5m.csv").write_text("ts,open\n1,2\n")
    assert depth_vault.seal({"panel": panel}, vault, ENV)["files"] == 0
    assert depth_vault.seal({"panel": panel}, vault, ENV, suffixes=(".csv",))["added_objects"] == 1
    out = depth_vault.restore({"panel": tmp_path / "back"}, vault, ENV)
    assert out["restored"] == 1 and (tmp_path / "back/SPY_5m.csv").read_text() == "ts,open\n1,2\n"


def test_label_copies_purchase_time_only_from_one_matching_ledger_entry(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    _write(cache / "features/third/mbo/gc/2026-07-30.csv.gz", "a\n")
    depth_vault.seal({"sweep": cache}, vault, ENV)
    _sources(vault, sweep={"origin": "new_acquisition", "provider": "Databento"})
    ledgers = _ledger(tmp_path, "sweep", "primary", [
        {"at": "2026-10-05T15:22:16+00:00", "what": "NQ mbp-10 2026-10-05 13:15-20:15Z"},
        {"at": "2026-10-05T08:00:00+00:00", "what": "GC mbo 2026-07-30"},  # wrong account for a third-account file
    ])
    assert depth_vault.label(vault, ledgers)["purchased_at_known"] == 1
    objects = json.loads((vault / "origins.json").read_text())["objects"]
    nq = objects["sweep/features/primary/mbp10/nq/2026-10-05.csv.gz"]
    assert nq["purchased_at"] == "2026-10-05T15:22:16+00:00" and nq["purchase_evidence"].endswith("#entries[0]")
    gc = objects["sweep/features/third/mbo/gc/2026-07-30.csv.gz"]
    assert gc["purchased_at"] is None and gc["purchase_evidence"] == "no ledger entry"
    assert objects["sweep/resilience/primary/nq/2026-10-05.csv.gz"]["purchase_evidence"] == "not a per-day feature file"


def test_ambiguous_ledger_matches_are_reported_not_guessed(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    _sources(vault, sweep={"origin": "new_acquisition", "provider": "Databento"})
    twice = [{"at": f"2026-10-0{i}T00:00:00+00:00", "what": "NQ mbp-10 2026-10-05"} for i in (5, 6)]
    depth_vault.label(vault, _ledger(tmp_path, "sweep", "primary", twice))
    nq = json.loads((vault / "origins.json").read_text())["objects"]["sweep/features/primary/mbp10/nq/2026-10-05.csv.gz"]
    assert nq["purchased_at"] is None and nq["purchase_evidence"] == "2 ledger entries match"


def test_preserved_originals_never_get_a_purchase_time(tmp_path):
    panel, vault = tmp_path / "panel", tmp_path / "vault"
    panel.mkdir()
    (panel / "SPY_5m.csv").write_text("ts\n1\n")
    depth_vault.seal({"panel": panel}, vault, ENV, suffixes=(".csv",))
    _sources(vault, panel={"origin": "preserved_original", "provider": "Polygon"})
    depth_vault.label(vault, tmp_path / "no-ledgers")
    rec = json.loads((vault / "origins.json").read_text())["objects"]["panel/SPY_5m.csv"]
    assert rec["origin"] == "preserved_original" and rec["purchased_at"] is None


def test_verify_authenticates_every_object_without_writing_plaintext(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    _sources(vault, sweep={"origin": "new_acquisition", "provider": "Databento"})
    depth_vault.label(vault, tmp_path / "no-ledgers")
    before = sorted(p.name for p in tmp_path.rglob("*"))
    receipt = depth_vault.verify(vault, ENV, ledger_dir=tmp_path / "no-ledgers")
    assert receipt["verdict"] == "OK" and receipt["caches"]["sweep"]["authenticated"] == 2
    assert receipt["plaintext_written"] is False and sorted(p.name for p in tmp_path.rglob("*")) == before


def test_verify_fails_on_tampering_and_on_unlabelled_objects(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    none = tmp_path / "no-ledgers"
    assert depth_vault.verify(vault, ENV, ledger_dir=none)["caches"]["sweep"]["label_mismatches"] == 2
    _sources(vault, sweep={"origin": "new_acquisition", "provider": "Databento"})
    depth_vault.label(vault, none)
    obj = next((vault / "objects").iterdir())
    obj.write_bytes(obj.read_bytes()[:-1] + bytes([obj.read_bytes()[-1] ^ 1]))
    receipt = depth_vault.verify(vault, ENV, ledger_dir=none)
    assert receipt["verdict"] == "FAILED" and receipt["failure_count"] == 1
    assert receipt["caches"]["sweep"]["authenticated"] == 1


def test_receipt_is_rewritten_only_on_change_or_daily(tmp_path):
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 10, 11, 6, tzinfo=timezone.utc)
    base = {"verdict": "OK", "caches": {"x": {"files": 1}}, "verified_at": t0.isoformat()}
    path = tmp_path / "receipt.json"
    assert depth_vault.write_receipt(path, base)
    later = dict(base, verified_at=(t0 + timedelta(hours=3)).isoformat())
    assert not depth_vault.write_receipt(path, later)
    assert depth_vault.write_receipt(path, dict(later, verdict="FAILED"))
    next_day = dict(base, verdict="FAILED", verified_at=(t0 + timedelta(hours=27)).isoformat())
    assert depth_vault.write_receipt(path, next_day)


def test_cli_verify_exits_nonzero_when_the_vault_fails(tmp_path, monkeypatch):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    monkeypatch.setenv("ICARUS_DATA_ARCHIVE_KEY", ENV["ICARUS_DATA_ARCHIVE_KEY"])
    with pytest.raises(SystemExit):  # objects exist but carry no origin labels
        depth_vault.main(["verify", "--vault", str(vault), "--out", str(tmp_path / "r.json")])
    assert json.loads((tmp_path / "r.json").read_text())["verdict"] == "FAILED"


def test_committed_origins_cover_every_vaulted_object():
    from pathlib import Path
    vault = Path(__file__).resolve().parent.parent / "data" / "depth_vault"
    manifest = json.loads((vault / "manifest.json").read_text())
    origins = json.loads((vault / "origins.json").read_text())
    want = {f"{c}/{rel}" for c, files in manifest["caches"].items() for rel in files}
    assert want <= set(origins["objects"]) and not origins["unlabelled_caches"]
    assert all(o["origin"] in depth_vault.ORIGINS for o in origins["objects"].values())


def test_verify_rejects_any_altered_label_field(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    _sources(vault, sweep={"origin": "new_acquisition", "provider": "Databento"})
    ledgers = _ledger(tmp_path, "sweep", "primary",
                      [{"at": "2026-10-05T15:22:16+00:00", "what": "NQ mbp-10 2026-10-05 13:15-20:15Z"}])
    depth_vault.label(vault, ledgers)
    assert depth_vault.verify(vault, ENV, ledger_dir=ledgers)["verdict"] == "OK"
    good = (vault / "origins.json").read_text()
    key = "sweep/features/primary/mbp10/nq/2026-10-05.csv.gz"
    for field, value in [("sha256", "0" * 64), ("bytes", 1), ("provider", "Other"),
                         ("origin", "preserved_original"), ("purchased_at", "2026-10-06T00:00:00+00:00"),
                         ("purchase_evidence", "invented")]:
        doc = json.loads(good)
        doc["objects"][key][field] = value
        (vault / "origins.json").write_text(json.dumps(doc))
        receipt = depth_vault.verify(vault, ENV, ledger_dir=ledgers)
        assert receipt["verdict"] == "FAILED", field
        assert receipt["label_mismatches"] == [f"{key}: {field}"], field
    doc = json.loads(good)
    doc["objects"]["sweep/not-in-manifest.csv.gz"] = doc["objects"][key]
    (vault / "origins.json").write_text(json.dumps(doc))
    assert depth_vault.verify(vault, ENV, ledger_dir=ledgers)["label_mismatch_count"] == 1


def _add_entry(vault, cache, rel, sha):
    manifest = json.loads((vault / "manifest.json").read_text())
    manifest["caches"][cache][rel] = {"sha256": sha, "bytes": 1}
    (vault / "manifest.json").write_text(json.dumps(manifest))


def test_restore_refuses_paths_that_climb_out_of_the_cache(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    sha = next((vault / "objects").iterdir()).stem
    _add_entry(vault, "sweep", "../escape_5m.csv", sha)
    target = tmp_path / "restore" / "sweep"
    with pytest.raises(ValueError, match="escapes its cache"):
        depth_vault.restore({"sweep": target}, vault, ENV)
    assert not (tmp_path / "restore" / "escape_5m.csv").exists()


def test_restore_refuses_symlink_escapes(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    sha = next((vault / "objects").iterdir()).stem
    outside, target = tmp_path / "outside", tmp_path / "restore"
    outside.mkdir()
    target.mkdir()
    (target / "sub").symlink_to(outside, target_is_directory=True)
    _add_entry(vault, "sweep", "sub/x_5m.csv", sha)
    with pytest.raises(ValueError, match="escapes its cache"):
        depth_vault.restore({"sweep": target}, vault, ENV)
    assert not any(outside.iterdir())


@pytest.mark.parametrize("rel", ["/abs/x.csv", "a/../../x.csv", "a\\..\\x.csv"])
def test_restore_refuses_absolute_and_backslash_paths(tmp_path, rel):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    _add_entry(vault, "sweep", rel, next((vault / "objects").iterdir()).stem)
    with pytest.raises(ValueError, match="escapes its cache"):
        depth_vault.restore({"sweep": tmp_path / "restore"}, vault, ENV)


def test_malformed_manifest_hash_is_refused(tmp_path):
    cache, vault = _cache(tmp_path), tmp_path / "vault"
    depth_vault.seal({"sweep": cache}, vault, ENV)
    _add_entry(vault, "sweep", "x_5m.csv", "../../manifest")
    with pytest.raises(ValueError, match="hash is malformed"):
        depth_vault.restore({"sweep": tmp_path / "restore"}, vault, ENV)
