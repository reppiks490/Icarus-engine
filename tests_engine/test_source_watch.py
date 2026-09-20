import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from icarus_engine.source_watch import SourceWatch


def test_opt_in_cadence_and_restart_use_saved_results(tmp_path):
    calls = []
    source = SimpleNamespace(root=tmp_path, collect=lambda name, options: calls.append(name) or {"status": "collected"})
    watch = SourceWatch(source)
    assert watch.tick() is None and calls == []
    watch.configure({"enabled": True, "jobs": [{"source": "coinbase", "interval_seconds": 5, "options": {}}]})
    assert watch.tick()["status"] == "collected"
    assert SourceWatch(source).tick() is None
    assert calls == ["coinbase"]
    assert watch.status()["collections"][0]["result"]["status"] == "collected"


def test_cross_process_claim_does_not_hold_db_during_network(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def collect(source, options):
        calls.append(source); entered.set()
        assert release.wait(5)
        return {"status": "collected"}
    sources = SimpleNamespace(root=tmp_path, collect=collect)
    first, second = SourceWatch(sources), SourceWatch(sources)
    first.configure({"enabled": True, "jobs": [{"source": "bls", "interval_seconds": 3600, "options": {}}]})
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(first.tick)
        try:
            assert entered.wait(3)
            assert second.tick() is None
            assert second.status()["collections"][0]["status"] == "collecting"
            second.configure({"enabled": False})
        finally:
            release.set()
        assert pending.result()["status"] == "collected"
    assert calls == ["bls"]
    assert first.tick() is None


def test_failure_is_visible_without_hot_loop_and_config_is_bounded(tmp_path):
    sources = SimpleNamespace(root=tmp_path, collect=lambda *a: {"status": "error", "error": "sequence gap"})
    watch = SourceWatch(sources)
    for config in ({"enabled": 1}, {"jobs": [{"source": "coinbase", "interval_seconds": 0, "options": {}}]},
                   {"jobs": [{"source": "untrusted", "interval_seconds": 3600, "options": {}}]}):
        with pytest.raises(ValueError):
            watch.configure(config)
    watch.configure({"enabled": True, "jobs": [{"source": "coinbase", "interval_seconds": 5, "options": {}}]})
    assert watch.tick()["status"] == "error"
    assert watch.tick() is None
    assert watch.status()["collections"][0]["result"]["error"] == "sequence gap"
