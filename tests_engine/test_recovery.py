from pathlib import Path
from types import SimpleNamespace

from icarus_engine.recovery import RecoveryWitness, snapshot, compare


class Em:
    def __init__(self,pos=1):
        self.open=[SimpleNamespace(entry_id="Long",direction=1,qty=1,entry_price=100.0,entry_ts=10)] if pos else []
        self._pending_entries=[SimpleNamespace(id="Long",direction=1,qty=1,limit=None,placed_bar=5)] if pos else []
    @property
    def position_size(self): return 1 if self.open else 0


def test_recovery_witness_roundtrip_and_replay_match(tmp_path):
    p=tmp_path/"state"/"recovery"/"NQ.json"
    a=RecoveryWitness(str(p)); a.write_live(100,"abc",Em())
    b=RecoveryWitness(str(p))
    b.observe_replay(100,"abc",Em())
    v=b.view()
    assert v["status"]=="MATCH"
    assert v["recovery_method"]=="DETERMINISTIC_MARKET_REPLAY"
    assert v["state_restore_enabled"] is False
    assert v["execution_authorized"] is False


def test_recovery_witness_detects_position_and_digest_divergence(tmp_path):
    p=tmp_path/"r.json"
    a=RecoveryWitness(str(p)); a.write_live(100,"abc",Em())
    b=RecoveryWitness(str(p)); b.observe_replay(100,"xyz",Em(pos=0))
    v=b.view()
    assert v["status"]=="DIVERGENCE"
    assert "decision_digest" in v["check"]["differences"]
    assert "position_size" in v["check"]["differences"]


def test_recovery_witness_marks_missing_reference_bar(tmp_path):
    p=tmp_path/"r.json"
    a=RecoveryWitness(str(p)); a.write_live(100,"abc",Em())
    b=RecoveryWitness(str(p)); b.observe_replay(120,"def",Em())
    assert b.view()["status"]=="REFERENCE_BAR_MISSING"


def test_runtime_and_ui_wire_recovery_as_non_restoring_assurance():
    rt=Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    ui=Path("icarus_engine/assurance-ui.js").read_text(encoding="utf-8")
    mod=Path("icarus_engine/recovery.py").read_text(encoding="utf-8")
    assert "RecoveryWitness" in rt and '"restart_recovery"' in rt
    assert "Restart replay recovery" in ui
    assert "state_restore_enabled" in mod
    for forbidden in (".entry(", ".exit(", ".close(", "PendingEntry", "ExitOrder"):
        assert forbidden not in mod
