"""Versioned PAPER configuration overlays; never writes owner input/preset files.

The injected ``boundary(asset)`` context holds the runtime locks and yields
``snapshot()``, ``validate(version_or_none)``, ``apply(version)``,
``restore(profile)`` and ``quarantine(reason)`` methods. Validation must locally
recheck approval, research qualification, history/configuration fingerprints,
warm state and absence of positions/pending orders. No provider calls belong
inside this boundary. Snapshots must contain everything needed for restoration,
including owner configuration hashes for the runtime's restart guard.

SQLite is the sole overlay source of truth. A durable prepared operation precedes
any runtime mutation. Interrupted operations block overlay loading and further
changes until explicit recovery restores their previous snapshot. A process/file
lock serializes writers across store instances; lock order is store then runtime.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import sqlite3
import threading
import time

from .advisory import (canonical_hash, canonical_json, strict_json, validate_patch,
                       _asset, _hash, _timestamp)


class ActivationError(ValueError):
    """A closed activation gate or an operation needing explicit recovery."""


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


class ActivationStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "activation.sqlite3"
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(os.path.normcase(str(self.path)), threading.RLock())
        with self._exclusive(), self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS activation_versions (
                    version_id TEXT PRIMARY KEY, asset TEXT NOT NULL,
                    body TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS activation_active (
                    asset TEXT PRIMARY KEY, body TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS activation_operations (
                    operation_id TEXT PRIMARY KEY, asset TEXT NOT NULL,
                    action TEXT NOT NULL, version_id TEXT,
                    status TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS activation_events (
                    seq INTEGER PRIMARY KEY, operation_id TEXT NOT NULL,
                    body TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS activation_version_update
                    BEFORE UPDATE ON activation_versions BEGIN
                    SELECT RAISE(ABORT, 'immutable activation version'); END;
                CREATE TRIGGER IF NOT EXISTS activation_version_delete
                    BEFORE DELETE ON activation_versions BEGIN
                    SELECT RAISE(ABORT, 'immutable activation version'); END;
                CREATE TRIGGER IF NOT EXISTS activation_event_update
                    BEFORE UPDATE ON activation_events BEGIN
                    SELECT RAISE(ABORT, 'immutable activation event'); END;
                CREATE TRIGGER IF NOT EXISTS activation_event_delete
                    BEFORE DELETE ON activation_events BEGIN
                    SELECT RAISE(ABORT, 'immutable activation event'); END;
            """)

    @contextmanager
    def _exclusive(self):
        with self._lock:
            with open(self.root / "activation.lock", "a+b") as fh:
                if fh.seek(0, os.SEEK_END) == 0:
                    fh.write(b"0")
                    fh.flush()
                deadline = time.monotonic() + 30
                while True:
                    try:
                        fh.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise ActivationError("activation store is busy") from None
                        time.sleep(.025)
                try:
                    yield
                finally:
                    fh.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA synchronous=FULL")
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _read(row):
        if row is None:
            return None
        value = strict_json(row["body"])
        if canonical_hash(value) != row["digest"]:
            raise ActivationError("activation record integrity mismatch")
        return value

    @staticmethod
    def _copy(value):
        return strict_json(canonical_json(value))

    def register(self, artifact):
        artifact = self._copy(artifact)
        candidate = artifact.get("candidate", {})
        version_id = _hash(artifact.get("candidate_hash"))
        asset = _asset(candidate.get("asset"))
        if (artifact.get("artifact_type") != "research_candidate"
                or artifact.get("research_qualified") is not True
                or canonical_hash(candidate) != version_id):
            raise ActivationError("version requires an intact qualified research artifact")
        validate_patch(candidate.get("inputs"))
        reviews = artifact.get("reviews", [])
        if (type(reviews) is not list or len(reviews) != 2
                or {(r.get("provider"), r.get("decision")) for r in reviews if type(r) is dict}
                   != {("openai", "recommend"), ("anthropic", "approve")}
                or any(r.get("candidate_hash") != version_id for r in reviews)):
            raise ActivationError("version requires OpenAI advice and Claude approval")
        version = {"version_id": version_id, "asset": asset, "artifact": artifact}
        with self._exclusive(), self._connect() as con:
            old = self._read(con.execute("SELECT * FROM activation_versions WHERE version_id=?", (version_id,)).fetchone())
            if old is not None and old != version:
                raise ActivationError("immutable version already has different content")
            con.execute("INSERT OR IGNORE INTO activation_versions VALUES (?,?,?,?)",
                        (version_id, asset, canonical_json(version), canonical_hash(version)))
        return version

    def version(self, version_id):
        _hash(version_id)
        with self._connect() as con:
            version = self._read(con.execute("SELECT * FROM activation_versions WHERE version_id=?", (version_id,)).fetchone())
        if version is None:
            raise ActivationError("unknown activation version")
        return version

    def _pending(self, con, asset):
        return [self._read(row) for row in con.execute(
            "SELECT * FROM activation_operations WHERE asset=? AND status IN ('prepared','recovery_required')",
            (asset,))]

    def active_profile(self, asset):
        _asset(asset)
        with self._exclusive(), self._connect() as con:
            if self._pending(con, asset):
                raise ActivationError("interrupted activation requires recovery before loading overlay")
            return self._read(con.execute("SELECT * FROM activation_active WHERE asset=?", (asset,)).fetchone())

    def status(self, asset=None, limit=100):
        if asset is not None:
            _asset(asset)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ActivationError("limit must be 1 to 1000")
        with self._connect() as con:
            rows = con.execute("SELECT * FROM activation_operations "
                               + ("WHERE asset=? " if asset else "")
                               + "ORDER BY rowid DESC LIMIT ?", (asset, limit) if asset else (limit,))
            operations = [self._read(row) for row in rows]
            rows = con.execute("SELECT * FROM activation_active" + (" WHERE asset=?" if asset else ""),
                               (asset,) if asset else ())
            active = [self._read(row) for row in rows]
        return {"mode": "paper", "active": active, "operations": operations,
                "execution_authorized": False}

    def _save_operation(self, con, operation):
        con.execute("INSERT INTO activation_operations VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(operation_id) DO UPDATE SET status=excluded.status,body=excluded.body,digest=excluded.digest",
                    (operation["operation_id"], operation["asset"], operation["action"], operation["version_id"],
                     operation["status"], canonical_json(operation), canonical_hash(operation)))
        event = {"operation_id": operation["operation_id"], "status": operation["status"],
                 "at": time.time(), "error": operation.get("error")}
        con.execute("INSERT INTO activation_events(operation_id,body,digest) VALUES (?,?,?)",
                    (operation["operation_id"], canonical_json(event), canonical_hash(event)))

    def _finish(self, operation, active):
        with self._connect() as con:
            if active is None:
                con.execute("DELETE FROM activation_active WHERE asset=?", (operation["asset"],))
            else:
                con.execute("INSERT INTO activation_active VALUES (?,?,?) ON CONFLICT(asset) "
                            "DO UPDATE SET body=excluded.body,digest=excluded.digest",
                            (operation["asset"], canonical_json(active), canonical_hash(active)))
            self._save_operation(con, operation)

    def activate(self, version_id, operation_id, boundary):
        version = self.version(version_id)
        return self._change(version["asset"], operation_id, "activate", version, boundary)

    def rollback(self, asset, operation_id, boundary):
        _asset(asset)
        return self._change(asset, operation_id, "rollback", None, boundary)

    def _change(self, asset, operation_id, action, version, boundary):
        if type(operation_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", operation_id):
            raise ActivationError("invalid operation id")
        version_id = version["version_id"] if version else None
        with self._exclusive():
            with self._connect() as con:
                old = self._read(con.execute("SELECT * FROM activation_operations WHERE operation_id=?", (operation_id,)).fetchone())
                if old:
                    if (old["asset"], old["action"], old["version_id"]) != (asset, action, version_id):
                        raise ActivationError("operation id already belongs to another request")
                    return old
                if self._pending(con, asset):
                    raise ActivationError("asset requires recovery before another activation")
                active = self._read(con.execute("SELECT * FROM activation_active WHERE asset=?", (asset,)).fetchone())
                previous_active = None
                if action == "rollback" and active is not None:
                    activation = self._read(con.execute("SELECT * FROM activation_operations WHERE operation_id=?",
                                                        (active["operation_id"],)).fetchone())
                    if activation is None or activation["status"] != "applied":
                        raise ActivationError("active overlay has no successful activation record")
                    previous_active = activation["previous_active"]
            operation = {"operation_id": operation_id, "asset": asset, "action": action,
                         "version_id": version_id, "status": "prepared", "started_at": time.time(),
                         "previous_active": active, "previous_profile": None, "error": None}
            with boundary(asset) as runtime:
                try:
                    if version and time.time() >= _timestamp(version["artifact"]["candidate"]["expires_at"]):
                        raise ActivationError("candidate expired before activation")
                    runtime.validate(version)
                    if action == "rollback" and active is None:
                        raise ActivationError("asset has no active overlay to roll back")
                    operation["previous_profile"] = self._copy(runtime.snapshot())
                except Exception as ex:
                    operation.update(status="rejected", error=f"{type(ex).__name__}: {ex}", finished_at=time.time())
                    with self._connect() as con:
                        self._save_operation(con, operation)
                    return operation
                # Commit the recovery record before the first runtime mutation.
                with self._connect() as con:
                    self._save_operation(con, operation)
                try:
                    if action == "activate":
                        runtime.apply(self._copy(version))
                        updated = {"asset": asset, "version_id": version_id,
                                   "profile": self._copy(runtime.snapshot()),
                                   "previous_profile": operation["previous_profile"],
                                   "previous_version_id": active["version_id"] if active else None,
                                   "operation_id": operation_id}
                    else:
                        runtime.restore(self._copy(active["previous_profile"]))
                        updated = previous_active
                    operation.update(status="applied" if action == "activate" else "rolled_back", finished_at=time.time())
                    self._finish(operation, updated)
                except Exception as ex:
                    operation.update(status="failed", error=f"{type(ex).__name__}: {ex}", finished_at=time.time())
                    try:
                        runtime.restore(self._copy(operation["previous_profile"]))
                    except Exception as restore_ex:
                        operation.update(status="recovery_required",
                                         error=operation["error"] + f"; restore failed: {type(restore_ex).__name__}: {restore_ex}")
                        runtime.quarantine(operation["error"])
                    # A failed durable commit must restore both runtime AND overlay.
                    # If this write also fails the prepared record remains recoverable.
                    self._finish(operation, active)
                return self._copy(operation)

    def recover(self, asset, boundary):
        """Restore interrupted work explicitly, under the same flat/warm guards."""
        _asset(asset)
        with self._exclusive():
            with self._connect() as con:
                pending = self._pending(con, asset)
            if not pending:
                return {"asset": asset, "status": "no_recovery_needed"}
            if len(pending) != 1:
                raise ActivationError("multiple pending operations; manual investigation required")
            operation = pending[0]
            with boundary(asset) as runtime:
                try:
                    runtime.validate(None)
                    runtime.restore(self._copy(operation["previous_profile"]))
                    operation.update(status="recovered", finished_at=time.time())
                    self._finish(operation, operation["previous_active"])
                except Exception as ex:
                    runtime.quarantine(f"activation recovery failed: {ex}")
                    raise ActivationError(f"activation recovery failed: {ex}") from ex
            return self._copy(operation)
