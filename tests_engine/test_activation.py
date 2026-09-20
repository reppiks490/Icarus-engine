"""Synthetic runtime boundary, real durable SQLite overlays and failure injection."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import sqlite3
import threading
import time

import pytest

from icarus_engine.activation import ActivationError, ActivationStore
from icarus_engine.advisory import canonical_hash, _iso


def artifact(votes=5):
    candidate = {"asset": "NQ", "inputs": {"conf_min_votes": votes},
                 "baseline_hash": "a" * 64, "dataset_hash": "b" * 64,
                 "expires_at": _iso(time.time() + 3600)}
    candidate_hash = canonical_hash(candidate)
    return {"artifact_type": "research_candidate", "research_qualified": True,
            "execution_authorized": False, "candidate_hash": candidate_hash,
            "candidate": candidate, "reviews": [
                {"provider": "openai", "decision": "recommend", "candidate_hash": candidate_hash},
                {"provider": "anthropic", "decision": "approve", "candidate_hash": candidate_hash}]}


class Runtime:
    def __init__(self):
        self.lock = threading.RLock()
        self.profile = {"base_inputs": {"conf_min_votes": 4}, "pts_scale": 1,
                        "sources": ["owner"], "owner_config_hash": "c" * 64}
        self.original = deepcopy(self.profile)
        self.warm, self.flat, self.pending = True, True, False
        self.baseline_hash, self.dataset_hash = "a" * 64, "b" * 64
        self.applied = self.restored = 0
        self.fail_apply = self.fail_restore = False
        self.crash = False
        self.paused = False
        self.enter_hook = None

    @contextmanager
    def boundary(self, asset):
        assert asset == "NQ"
        with self.lock:
            if self.enter_hook:
                self.enter_hook()
            yield self

    def snapshot(self):
        return deepcopy(self.profile)

    def validate(self, version):
        if not self.warm or not self.flat or self.pending:
            raise ValueError("not warm and flat without pending orders")
        if version:
            candidate = version["artifact"]["candidate"]
            if (candidate["baseline_hash"], candidate["dataset_hash"]) != (self.baseline_hash, self.dataset_hash):
                raise ValueError("stale candidate")

    def apply(self, version):
        self.applied += 1
        self.profile["base_inputs"].update(version["artifact"]["candidate"]["inputs"])
        if self.crash:
            raise SystemExit("simulated process interruption")
        if self.fail_apply:
            self.profile["pts_scale"] = 999
            raise RuntimeError("rewarm failed after partial mutation")

    def restore(self, profile):
        self.restored += 1
        if self.fail_restore:
            raise RuntimeError("restore failed")
        self.profile = deepcopy(profile)

    def quarantine(self, reason):
        self.paused = True


@pytest.fixture
def setup(tmp_path):
    store = ActivationStore(tmp_path / "research" / "activation")
    return store, Runtime(), store.register(artifact())


def test_apply_rollback_and_restart_preserve_original_files(setup, tmp_path):
    store, runtime, version = setup
    owner = tmp_path / "inputs.NQ.json"
    preset = tmp_path / "presets" / "owner.json"
    preset.parent.mkdir()
    owner.write_bytes(b'{"conf_min_votes":4}')
    preset.write_bytes(b'{"pts_scale":1}')
    expected = owner.read_bytes(), preset.read_bytes()
    result = store.activate(version["version_id"], "apply_1", runtime.boundary)
    assert result["status"] == "applied"
    assert runtime.profile["base_inputs"]["conf_min_votes"] == 5
    reopened = ActivationStore(store.root)
    assert reopened.active_profile("NQ")["profile"] == runtime.profile
    assert reopened.active_profile("NQ")["profile"]["owner_config_hash"] == "c" * 64
    assert reopened.rollback("NQ", "rollback_1", runtime.boundary)["status"] == "rolled_back"
    assert runtime.profile == runtime.original
    assert reopened.active_profile("NQ") is None
    assert (owner.read_bytes(), preset.read_bytes()) == expected


@pytest.mark.parametrize("field", ["warm", "flat", "pending", "baseline_hash", "dataset_hash"])
def test_apply_revalidates_at_actual_locked_boundary(setup, field):
    store, runtime, version = setup
    value = {"warm": False, "flat": False, "pending": True,
             "baseline_hash": "d" * 64, "dataset_hash": "e" * 64}[field]
    runtime.enter_hook = lambda: setattr(runtime, field, value)
    result = store.activate(version["version_id"], "stale", runtime.boundary)
    assert result["status"] == "rejected"
    assert runtime.applied == 0
    assert store.active_profile("NQ") is None
    assert store.status("NQ")["operations"][0]["status"] == "rejected"


def test_expired_candidate_rejected_even_if_boundary_accepts(setup):
    store, runtime, _ = setup
    expired = artifact()
    expired["candidate"]["expires_at"] = _iso(time.time() - 1)
    expired["candidate_hash"] = canonical_hash(expired["candidate"])
    for review in expired["reviews"]:
        review["candidate_hash"] = expired["candidate_hash"]
    version = store.register(expired)
    assert store.activate(version["version_id"], "expired", runtime.boundary)["status"] == "rejected"
    assert runtime.applied == 0


def test_partial_rewarm_failure_restores_previous_profile(setup):
    store, runtime, version = setup
    runtime.fail_apply = True
    result = store.activate(version["version_id"], "partial", runtime.boundary)
    assert result["status"] == "failed"
    assert runtime.profile == runtime.original
    assert runtime.restored == 1
    assert store.active_profile("NQ") is None


def test_failed_restore_quarantines_until_explicit_recovery(setup):
    store, runtime, version = setup
    runtime.fail_apply = runtime.fail_restore = True
    result = store.activate(version["version_id"], "broken", runtime.boundary)
    assert result["status"] == "recovery_required"
    assert runtime.paused
    with pytest.raises(ActivationError, match="recovery"):
        store.active_profile("NQ")
    with pytest.raises(ActivationError, match="recovery"):
        store.activate(version["version_id"], "another", runtime.boundary)
    with pytest.raises(ActivationError, match="recovery failed"):
        store.recover("NQ", runtime.boundary)
    runtime.fail_apply = runtime.fail_restore = False
    assert store.recover("NQ", runtime.boundary)["status"] == "recovered"
    assert runtime.profile == runtime.original
    assert store.active_profile("NQ") is None


def test_interruption_reopens_fail_closed_then_restores_snapshot(setup):
    store, runtime, version = setup
    runtime.crash = True
    with pytest.raises(SystemExit):
        store.activate(version["version_id"], "crash", runtime.boundary)
    reopened = ActivationStore(store.root)
    with pytest.raises(ActivationError, match="interrupted"):
        reopened.active_profile("NQ")
    runtime.crash = False
    assert reopened.recover("NQ", runtime.boundary)["status"] == "recovered"
    assert runtime.profile == runtime.original
    assert reopened.recover("NQ", runtime.boundary)["status"] == "no_recovery_needed"


def test_commit_failure_after_rewarm_restores_runtime_and_prior_overlay(setup, monkeypatch):
    store, runtime, version = setup
    store.activate(version["version_id"], "first", runtime.boundary)
    old_profile = runtime.snapshot()
    old_active = store.active_profile("NQ")
    second = store.register(artifact(6))
    finish = store._finish
    def fail_success_commit(operation, active):
        if operation["status"] == "applied":
            raise OSError("disk full")
        return finish(operation, active)
    monkeypatch.setattr(store, "_finish", fail_success_commit)
    assert store.activate(second["version_id"], "second", runtime.boundary)["status"] == "failed"
    assert runtime.profile == old_profile
    assert store.active_profile("NQ") == old_active


def test_persistent_write_failure_retains_prepared_recovery_record(setup, monkeypatch):
    store, runtime, version = setup
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(store, "_finish", fail)
    with pytest.raises(OSError, match="disk full"):
        store.activate(version["version_id"], "disk", runtime.boundary)
    assert runtime.profile == runtime.original
    reopened = ActivationStore(store.root)
    assert reopened.status("NQ")["operations"][0]["status"] == "prepared"
    assert reopened.recover("NQ", runtime.boundary)["status"] == "recovered"


def test_idempotent_concurrent_requests_across_store_instances(setup):
    store, runtime, version = setup
    stores = [ActivationStore(store.root) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda instance: instance.activate(version["version_id"], "same", runtime.boundary), stores))
    assert all(result == results[0] for result in results)
    assert runtime.applied == 1
    assert len(store.status()["operations"]) == 1
    with pytest.raises(ActivationError, match="another request"):
        store.rollback("NQ", "same", runtime.boundary)


def test_multi_version_rollback_follows_lineage_without_nested_growth(setup):
    store, runtime, version = setup
    for i in range(20):
        item = store.register(artifact(5 + i % 2))
        assert store.activate(item["version_id"], f"apply_{i}", runtime.boundary)["status"] == "applied"
    for i in reversed(range(20)):
        assert store.rollback("NQ", f"rollback_{i}", runtime.boundary)["status"] == "rolled_back"
    assert runtime.profile == runtime.original
    assert store.active_profile("NQ") is None


def test_rollback_rejected_when_position_open(setup):
    store, runtime, version = setup
    store.activate(version["version_id"], "first", runtime.boundary)
    profile = runtime.snapshot()
    runtime.flat = False
    assert store.rollback("NQ", "unsafe", runtime.boundary)["status"] == "rejected"
    assert runtime.profile == profile


def test_immutable_versions_and_integrity_checks(setup):
    store, _, version = setup
    assert store.register(version["artifact"]) == version
    changed = deepcopy(version["artifact"])
    changed["note"] = "different immutable export"
    with pytest.raises(ActivationError, match="immutable"):
        store.register(changed)
    with sqlite3.connect(store.path) as con:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            con.execute("UPDATE activation_versions SET asset='ES'")
        con.execute("DROP TRIGGER activation_version_update")
        con.execute("UPDATE activation_versions SET digest=?", ("0" * 64,))
    with pytest.raises(ActivationError, match="integrity"):
        store.version(version["version_id"])


@pytest.mark.parametrize("mutation", ["unqualified", "unapproved", "modified"])
def test_register_rejects_incomplete_or_changed_artifacts(tmp_path, mutation):
    store = ActivationStore(tmp_path)
    value = artifact()
    if mutation == "unqualified":
        value["research_qualified"] = False
    elif mutation == "unapproved":
        value["reviews"].pop()
    else:
        value["candidate"]["inputs"]["conf_min_votes"] = 6
    with pytest.raises(ActivationError):
        store.register(value)
