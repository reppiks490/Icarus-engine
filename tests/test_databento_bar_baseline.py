import gzip
import json

import pytest

from tools.databento_bar_baseline import prepare


def _fixture(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in ("databento_es_5m.csv.gz", "databento_hist_nq_5m.csv.gz"):
        with gzip.open(cache / name, "wb") as stream:
            stream.write(b"ts,open,high,low,close,volume\n2026-10-16,1,2,1,2,3\n")
    feeds = tmp_path / "feeds.json"
    feeds.write_text(json.dumps({"feeds": {
        "databento_es_5m": {"kind": "databento", "status": "ok", "notes": ["account=primary"]},
        "databento_dx_5m": {"kind": "databento", "status": "error", "notes": []},
    }}))
    history = tmp_path / "history.json"
    history.write_text(json.dumps({"roots": {"NQ": {"finished": True, "account": "third"}}}))
    vault = tmp_path / "vault"
    vault.mkdir()
    return cache, feeds, history, vault


def test_stages_only_successful_account_scoped_bars_and_never_replaces_a_baseline(tmp_path):
    cache, feeds, history, vault = _fixture(tmp_path)
    first = prepare(cache, tmp_path / "stage1", feeds, history, vault)
    assert first == {"candidates": 2, "staged": 2, "already_vaulted": 0,
                     "staged_by_account": {"primary": 1, "secondary": 0, "third": 1}}
    assert (tmp_path / "stage1/bars_primary/databento_es_5m.csv.gz").is_file()
    assert (tmp_path / "stage1/bars_third/databento_hist_nq_5m.csv.gz").is_file()

    (vault / "manifest.json").write_text(json.dumps({"caches": {
        "bars_primary": {"databento_es_5m.csv.gz": {"sha256": "old"}},
        "bars_third": {"databento_hist_nq_5m.csv.gz": {"sha256": "old"}},
    }}))
    (cache / "databento_es_5m.csv.gz").unlink()
    second = prepare(cache, tmp_path / "stage2", feeds, history, vault)
    assert second["staged"] == 0 and second["already_vaulted"] == 2


def test_missing_unarchived_paid_bar_fails_instead_of_claiming_a_baseline(tmp_path):
    cache, feeds, history, vault = _fixture(tmp_path)
    (cache / "databento_es_5m.csv.gz").unlink()
    with pytest.raises(FileNotFoundError, match="baseline source missing"):
        prepare(cache, tmp_path / "stage", feeds, history, vault)


def test_account_baselines_encrypt_and_restore_to_one_feed_cache(tmp_path):
    pytest.importorskip("cryptography")
    from tools import depth_vault

    cache, feeds, history, vault = _fixture(tmp_path)
    stage = tmp_path / "stage"
    prepare(cache, stage, feeds, history, vault)
    env = {"DATABENTO_API_KEY": "synthetic-primary-key"}
    depth_vault.seal({"bars_primary": stage / "bars_primary",
                      "bars_third": stage / "bars_third"}, vault, env)
    restored = tmp_path / "restored"
    assert depth_vault.restore({"bars_primary": restored,
                                "bars_third": restored}, vault, env)["restored"] == 2
    for name in ("databento_es_5m.csv.gz", "databento_hist_nq_5m.csv.gz"):
        assert (restored / name).read_bytes() == (cache / name).read_bytes()
