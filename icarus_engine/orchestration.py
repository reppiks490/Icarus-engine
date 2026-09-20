"""Durable bounded analysis jobs; models provide evidence, never runtime access.

Every paid stage reserves its entire input-byte/output-token upper bound before
transport. An interrupted/uncertain call is never retried automatically. Separate
roles have isolated requests and cannot send tools, change inputs or place orders.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import time

from . import advisory
from .advisory import canonical_hash, canonical_json, strict_json


ROLES = ("source-auditor", "regime-analyst", "risk-auditor")


@dataclass(frozen=True)
class Budget:
    max_daily_calls: int = 25
    max_daily_reserved_tokens: int = 500000
    max_context_bytes: int = 48000
    max_output_tokens: int = 2048

    def __post_init__(self):
        for name, maximum in (("max_daily_calls", 1000), ("max_daily_reserved_tokens", 10000000),
                              ("max_context_bytes", 48000), ("max_output_tokens", 2048)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer from 1 to {maximum}")
        if self.max_output_tokens != 2048:
            raise ValueError("provider transport currently enforces exactly 2048 maximum output tokens")


class WorkflowJournal:
    def __init__(self, root, budget=None):
        self.path = Path(root) / "workflow.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.budget = budget or Budget()
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL, result TEXT, error TEXT,
                    cancelled INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS workflow_stages (
                    job TEXT NOT NULL, stage TEXT NOT NULL, input_hash TEXT NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL, day TEXT NOT NULL,
                    reserved_tokens INTEGER NOT NULL, status TEXT NOT NULL,
                    created REAL NOT NULL, finished REAL, result TEXT, error TEXT,
                    PRIMARY KEY(job,stage));
            """)

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def create(self, request):
        raw = canonical_json(request)
        ident = canonical_hash(request)
        now = time.time()
        with self._connect() as con:
            row = con.execute("SELECT id FROM workflows WHERE id=?", (ident,)).fetchone()
            if row:
                return ident, False
            con.execute("INSERT INTO workflows(id,request,status,created,updated) VALUES (?,?,?,?,?)",
                        (ident, raw, "queued", now, now))
        return ident, True

    def claim(self, ident):
        with self._connect() as con:
            changed = con.execute("UPDATE workflows SET status='running',updated=? WHERE id=? AND status='queued' AND cancelled=0",
                                  (time.time(), ident)).rowcount
        return changed == 1

    def cancel(self, ident):
        with self._connect() as con:
            if not con.execute("UPDATE workflows SET cancelled=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,updated=? WHERE id=?", (time.time(), ident)).rowcount:
                raise ValueError("unknown workflow")
        return self.get(ident)

    def is_cancelled(self, ident):
        with self._connect() as con:
            row = con.execute("SELECT cancelled FROM workflows WHERE id=?", (ident,)).fetchone()
        return row is None or bool(row[0])

    def finish(self, ident, status, result=None, error=None):
        if status not in {"complete", "rejected", "cancelled", "blocked", "error"}:
            raise ValueError("invalid workflow terminal state")
        with self._connect() as con:
            con.execute("UPDATE workflows SET status=?,updated=?,result=?,error=? WHERE id=?",
                        (status, time.time(), canonical_json(result) if result is not None else None, error, ident))

    def get(self, ident):
        with self._connect() as con:
            row = con.execute("SELECT * FROM workflows WHERE id=?", (ident,)).fetchone()
            if row is None:
                raise ValueError("unknown workflow")
            stages = con.execute("SELECT * FROM workflow_stages WHERE job=? ORDER BY created,stage", (ident,)).fetchall()
        result = dict(row)
        result["request"] = json.loads(result["request"])
        result["result"] = json.loads(result["result"]) if result["result"] else None
        result["stages"] = []
        for stage in stages:
            item = dict(stage)
            item["result"] = json.loads(item["result"]) if item["result"] else None
            result["stages"].append(item)
        return result

    def status(self):
        day = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as con:
            used = con.execute("SELECT count(*),coalesce(sum(reserved_tokens),0) FROM workflow_stages WHERE day=?", (day,)).fetchone()
            rows = con.execute("SELECT id,status,created,updated,error,cancelled FROM workflows ORDER BY created DESC LIMIT 32").fetchall()
        return {"budget": asdict(self.budget), "utc_day": day, "reserved_calls": used[0],
                "reserved_tokens": used[1], "jobs": [dict(row) for row in rows],
                "budget_unit": "conservative input bytes plus maximum output tokens; not a dollar estimate"}

    def run_stage(self, job, stage, context, provider, call):
        if provider not in advisory._PROVIDERS:
            raise ValueError("unsupported provider")
        _, key_name, model_name = advisory._PROVIDERS[provider]
        import os
        model = os.environ.get(model_name, "")
        if not os.environ.get(key_name) or not model:
            raise ValueError(f"provider {provider} is not configured")
        raw = canonical_json(context)
        size = len(raw.encode("utf-8"))
        if size > self.budget.max_context_bytes:
            raise ValueError("analysis context exceeds bounded request size")
        # Includes provider instructions and serialization framing conservatively.
        reserved = size + 8192 + self.budget.max_output_tokens
        input_hash = canonical_hash({"context": context, "provider": provider, "model": model,
                                     "budget": asdict(self.budget)})
        day = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as con:
            row = con.execute("SELECT * FROM workflow_stages WHERE job=? AND stage=?", (job, stage)).fetchone()
            if row:
                if row["input_hash"] != input_hash:
                    raise ValueError("stage identity changed")
                if row["status"] == "complete":
                    return json.loads(row["result"])
                raise ValueError("stage already attempted; uncertain calls are never retried automatically")
            state = con.execute("SELECT status,cancelled FROM workflows WHERE id=?", (job,)).fetchone()
            if state is None or state["status"] != "running" or state["cancelled"]:
                raise ValueError("workflow is not running or was cancelled")
            used = con.execute("SELECT count(*),coalesce(sum(reserved_tokens),0) FROM workflow_stages WHERE day=?", (day,)).fetchone()
            if used[0] >= self.budget.max_daily_calls or used[1] + reserved > self.budget.max_daily_reserved_tokens:
                raise ValueError("daily model budget exhausted")
            con.execute("INSERT INTO workflow_stages(job,stage,input_hash,provider,model,day,reserved_tokens,status,created) VALUES (?,?,?,?,?,?,?,?,?)",
                        (job, stage, input_hash, provider, model, day, reserved, "attempted", time.time()))
        try:
            result = call()
            encoded = canonical_json(result)
        except Exception:
            with self._connect() as con:
                con.execute("UPDATE workflow_stages SET status='outcome_unknown',finished=?,error=? WHERE job=? AND stage=?",
                            (time.time(), "Provider stage did not return verified evidence; no automatic retry.", job, stage))
            raise
        with self._connect() as con:
            con.execute("UPDATE workflow_stages SET status='complete',finished=?,result=? WHERE job=? AND stage=?",
                        (time.time(), encoded, job, stage))
        return result


class AnalysisService:
    def __init__(self, workspace):
        self.workspace = workspace
        self.journal = WorkflowJournal(workspace.root)
        self._threads = {}
        self._lock = threading.RLock()

    def stop(self):
        with self._lock:
            identifiers = list(self._threads)
        for ident in identifiers:
            self.journal.cancel(ident)

    def start(self, request):
        if type(request) is not dict or set(request) != {"job", "evidence_ids", "rationale", "apply"}:
            raise ValueError("analysis requires job, evidence_ids, rationale and apply only")
        if type(request["apply"]) is not bool:
            raise ValueError("apply must be Boolean")
        # Resolve deterministic qualification and source freshness before any paid call.
        context = self.workspace.analysis_context(request)
        bound = {"request": request, "context_hash": canonical_hash(context)}
        ident, created = self.journal.create(bound)
        if created:
            thread = threading.Thread(target=self._work, args=(ident, request, context),
                                      name="analysis-" + ident[:12], daemon=True)
            with self._lock:
                self._threads[ident] = thread
            thread.start()
        return self.job(ident)

    def job(self, ident):
        row = self.journal.get(ident)
        with self._lock:
            worker = self._threads.get(ident)
        if row["status"] in ("running", "queued") and (worker is None or not worker.is_alive()):
            row["status"] = "unowned"
            row["error"] = "No worker in this process; it may be interrupted or owned by another process. No automatic retry."
        return row

    def status(self):
        status = self.journal.status()
        rows = []
        for item in status["jobs"]:
            current = self.job(item["id"])
            rows.append({key: current[key] for key in item})
        status["jobs"] = rows
        return status

    def _work(self, ident, request, context):
        if not self.journal.claim(ident):
            with self._lock:
                self._threads.pop(ident, None)
            return
        try:
            def analyse(role):
                item = {"role": role, "context": context}
                return self.journal.run_stage(ident, role, item, "openai", lambda:
                    advisory._provider_review("openai", {"candidate_hash": canonical_hash(item),
                        "analysis_context": item}, [], [], analysis_role=role))
            with ThreadPoolExecutor(max_workers=len(ROLES), thread_name_prefix="icarus-analyst") as pool:
                reports = dict(zip(ROLES, pool.map(analyse, ROLES)))
            if self.journal.is_cancelled(ident):
                self.journal.finish(ident, "cancelled")
                return
            if any(report["decision"] != "recommend" for report in reports.values()):
                self.journal.finish(ident, "rejected", {"analyses": reports})
                return
            bundle = {"context_hash": canonical_hash(context), "roles": reports, "workflow_id": ident}
            proposal = self.workspace.propose_analysis(request, bundle)
            pid = proposal["proposal_id"]
            for provider in ("openai", "anthropic"):
                if self.journal.is_cancelled(ident):
                    self.journal.finish(ident, "cancelled", {"proposal_id": pid})
                    return
                current = self.workspace.ledger.get_proposal(pid)
                proposal = self.journal.run_stage(ident, provider + "-review", current, provider,
                                                 lambda p=provider: self.workspace.ledger.review(pid, p))
                if proposal["state"] == "rejected":
                    self.journal.finish(ident, "rejected", {"proposal_id": pid})
                    return
            artifact = self.workspace.export(pid)
            result = {"proposal_id": pid, "artifact": artifact, "applied": False}
            if request["apply"] and not self.journal.is_cancelled(ident):
                result["activation"] = self.workspace.activate({"proposal_id": pid, "operation_id": ident})
                result["applied"] = result["activation"].get("status") == "applied"
                if not result["applied"]:
                    self.journal.finish(ident, "blocked", result, "Paper activation gate did not apply the candidate.")
                    return
            self.journal.finish(ident, "cancelled" if self.journal.is_cancelled(ident) else "complete", result)
        except Exception as ex:
            # Provider exceptions can contain secrets. Persist only trusted type/status.
            self.journal.finish(ident, "blocked", error=type(ex).__name__ + ": analysis stopped; inspect stage status and provider configuration.")
        finally:
            with self._lock:
                self._threads.pop(ident, None)
