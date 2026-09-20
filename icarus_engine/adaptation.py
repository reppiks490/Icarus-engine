"""Opt-in, durable per-asset research and paper adaptation scheduler."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .advisory import _PROVIDERS, _iso, _now
from .research import Policy, Windows, _grid
from .runtime import validate_values
from .pine.timeframe import Aggregator
from .strategy.meta import load_meta
from .process_identity import identity as process_identity


DEFAULT_CONFIG = {"enabled": False, "assets": [], "apply": True, "cadence_seconds": 3600,
                  "train_bars": 600, "validation_bars": 200, "holdout_bars": 200,
                  "policy": {"max_trials": 16, "max_seconds": 120}, "grids": {}, "max_evidence": 8}


class AdaptationScheduler:
    def __init__(self, workspace):
        self.workspace = workspace
        self.path = Path(workspace.root) / "adaptation.json"
        self.lock_path = self.path.with_suffix(".lock.sqlite3")
        self._owner = uuid.uuid4().hex
        self._process = {"pid": os.getpid(), "birth": process_identity(os.getpid())}
        self._thread = None
        self._stop = threading.Event()
        self._mutex = threading.RLock()
        self._transaction = threading.local()

    @contextmanager
    def _locked(self):
        # tick holds the cross-process transaction across its read/claim/write.
        # Helpers may inspect or update state in that same transaction.
        if getattr(self._transaction, "active", False):
            yield
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.lock_path), timeout=10)
        try:
            con.execute("BEGIN IMMEDIATE")
            self._transaction.active = True
            yield
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            self._transaction.active = False
            con.close()

    def _read(self):
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"config": dict(DEFAULT_CONFIG), "assets": {}, "cursor": 0, "active": None}

    def _write(self, state):
        temp = self.path.with_name(self.path.name + "." + self._owner + ".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, self.path)

    def configure(self, partial):
        if type(partial) is not dict or set(partial) - set(DEFAULT_CONFIG):
            raise ValueError("unknown adaptation configuration field")
        with self._mutex, self._locked():
            state = self._read()
            config = {**state["config"], **partial}
            for key in ("enabled", "apply"):
                if type(config[key]) is not bool:
                    raise ValueError(f"{key} must be Boolean")
            if (type(config["assets"]) is not list or len(config["assets"]) > 32
                    or any(type(a) is not str or a not in self.workspace.port.runners for a in config["assets"])
                    or len(set(config["assets"])) != len(config["assets"])):
                raise ValueError("assets must be unique running asset names")
            for key, low, high in (("cadence_seconds", 60, 86400), ("train_bars", 2, 10000),
                                   ("validation_bars", 2, 10000), ("holdout_bars", 2, 10000),
                                   ("max_evidence", 1, 32)):
                if type(config[key]) is not int or not low <= config[key] <= high:
                    raise ValueError(f"{key} is outside supported bounds")
            if type(config["policy"]) is not dict:
                raise ValueError("policy must be an object")
            Policy(**config["policy"])
            if type(config["grids"]) is not dict or len(config["grids"]) > 32:
                raise ValueError("grids must be an asset map")
            for asset, grid in config["grids"].items():
                if asset not in self.workspace.port.runners:
                    raise ValueError("grid names an unknown asset")
                _grid(grid)
                if any(name.startswith("rate_") for name in grid):
                    raise ValueError("RATE inputs are protected")
            state["config"] = config
            self._write(state)
        return self.status()

    def status(self):
        with self._mutex, self._locked():
            state = self._read()
        active = state.get("active")
        if active and active.get("owner") != self._owner:
            uncertain = active.get("stage") in ("study_intent", "analysis_intent")
            active = {**active, "status": "unowned_launch" if uncertain else "unowned",
                      "note": "Another scheduler owns this job, or its process stopped. Automatic relaunch is blocked."}
        return {**state, "active": active, "running": bool(self._thread and self._thread.is_alive())}

    def _providers_ready(self):
        for _, key, model in _PROVIDERS.values():
            if not os.environ.get(key) or not os.environ.get(model):
                return False
        return True

    def _budget_ready(self):
        journal = self.workspace.analysis.journal
        status = journal.status()
        budget = status["budget"]
        # Five possible calls: three specialist roles plus two ordered reviews.
        max_tokens = budget["max_context_bytes"] + 8192 + budget["max_output_tokens"]
        return (status["reserved_calls"] + 5 <= budget["max_daily_calls"]
                and status["reserved_tokens"] + 5 * max_tokens <= budget["max_daily_reserved_tokens"])

    @staticmethod
    def _watermark(path, asset):
        if not path.exists():
            return -1
        with sqlite3.connect(str(path), timeout=10) as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            revealed = con.execute("SELECT until_ts FROM revealed WHERE asset=?", (asset,)).fetchone() if "revealed" in tables else None
            claimed = con.execute("SELECT MAX(end) FROM holdouts WHERE asset=?", (asset,)).fetchone() if "holdouts" in tables else None
        return max(revealed[0] if revealed else -1, claimed[0] if claimed and claimed[0] is not None else -1)

    @staticmethod
    def _auto_grid(runner, cursor):
        current = runner.inputs_base.to_dict()
        meta = {entry["name"]: entry for entry in load_meta()}
        eligible = []
        for name, value in current.items():
            if name.startswith("rate_"):
                continue
            entry = meta.get(name, {})
            choices = []
            if type(value) is bool:
                choices = [not value]
            elif entry.get("options"):
                choices = [v for v in entry["options"] if v != value][:2]
            elif type(value) in (int, float) and ("minval" in entry or "maxval" in entry):
                step = entry.get("step", 1 if type(value) is int else max(abs(value) * .1, .01))
                choices = [value - step, value + step]
            # Never synthesize dates, sessions, free strings or HTF names.
            if name.startswith("htf_tf_"):
                choices = []
            good = []
            for choice in choices:
                if type(value) is int and type(choice) is float and choice.is_integer():
                    choice = int(choice)
                if choice == value or choice in good:
                    continue
                try:
                    validate_values({name: choice})
                except ValueError:
                    continue
                good.append(choice)
            if good:
                eligible.append((name, good[:2]))
        if not eligible:
            raise ValueError("no eligible bounded input neighbors")
        return dict([eligible[cursor % len(eligible)]]), cursor + 1

    def _prepare(self, asset, config, cursor):
        if not self._providers_ready():
            raise ValueError("OpenAI and Anthropic provider credentials/models are not configured")
        if not self._budget_ready():
            raise ValueError("daily budget cannot reserve the full review chain")
        evidence = self.workspace.ledger.events_as_of(asset, _iso(_now()))
        if not evidence:
            raise ValueError("no fresh actual ledger evidence for asset")
        runner = self.workspace.port.runners[asset]
        with runner.lock:
            if not runner.warm:
                raise ValueError("asset is still warming")
            # The display deque is capped at 900; rebuild closed chart buckets
            # from the longer retained sub-bar cache for the default 1000-bar study.
            agg = Aggregator(runner.chart_minutes, runner.cal.bucket_start, runner.cal.bucket_end)
            bars = []
            for bar, sub_minutes in runner.subbars:
                if runner.cal.intraday_open(bar.ts) and runner.chart_minutes % sub_minutes == 0:
                    bars.extend(agg.push(bar, sub_minutes))
            grid, next_cursor = (config["grids"][asset], cursor) if asset in config["grids"] else self._auto_grid(runner, cursor)
            minutes = runner.chart_minutes
        total = config["train_bars"] + config["validation_bars"] + config["holdout_bars"] + 2
        if len(bars) < total:
            raise ValueError("insufficient closed chart bars")
        bars = bars[-total:]
        t, v, h = config["train_bars"], config["validation_bars"], config["holdout_bars"]
        cal = runner.cal
        windows = Windows(bars[0].ts, cal.bucket_end(bars[t - 1].ts, minutes),
                          bars[t + 1].ts, cal.bucket_end(bars[t + v].ts, minutes),
                          bars[t + v + 2].ts, cal.bucket_end(bars[-1].ts, minutes))
        if windows.holdout_start <= self._watermark(self.workspace.root / "holdouts.sqlite3", asset):
            raise ValueError("no new held-out interval beyond durable revealed/claimed watermark")
        return {"asset": asset, "grid": grid, "windows": asdict(windows), "policy": config["policy"]}, [e["event_id"] for e in evidence[:config["max_evidence"]]], next_cursor

    def tick(self):
        with self._mutex, self._locked():
            with self._locked():
                state = self._read()
                config = state["config"]
                active = state.get("active")
            if not config["enabled"]:
                return self.status()
            if active and active.get("owner") != self._owner:
                owner = active.get("process", {})
                current = process_identity(owner.get("pid"))
                if current is None or not owner.get("birth") or current == owner["birth"]:
                    return self.status()
                # Only a confirmed exit or PID reuse authorizes abandonment.
                # Durable paid-call reservations remain consumed, and the same
                # frozen interval is not automatically studied again.
                if active.get("workflow"):
                    self.workspace.analysis.journal.cancel(active["workflow"])
                return self._finish(active, "interrupted", "Previous scheduler process exited; uncertain stages were not retried.")
            if active:
                return self._advance(active)
            assets = config["assets"] or list(self.workspace.port.runners)
            if not assets:
                return self.status()
            start = state["cursor"] % len(assets)
            for offset in range(len(assets)):
                asset = assets[(start + offset) % len(assets)]
                prior = state["assets"].get(asset, {})
                if time.time() < prior.get("next_due", 0):
                    continue
                try:
                    request, ids, dimension = self._prepare(asset, config, prior.get("dimension", 0))
                    # A completed no-candidate study on the same frozen data is final.
                    if max(prior.get("no_candidate_cutoff", -1), prior.get("last_attempt_cutoff", -1)) >= request["windows"]["holdout_end"]:
                        continue
                except ValueError as ex:
                    prior.update(status="blocked", reason=str(ex), next_due=time.time() + config["cadence_seconds"])
                    state["assets"][asset] = prior
                    continue
                active = {"asset": asset, "stage": "study_intent", "owner": self._owner,
                          "process": self._process,
                          "apply": config["apply"],
                          "request": request, "evidence_ids": ids, "started": time.time()}
                state["active"] = active
                state["cursor"] = (start + offset + 1) % len(assets)
                prior.update(status="study_launch", dimension=dimension)
                state["assets"][asset] = prior
                with self._locked():
                    self._write(state)
                try:
                    response = self.workspace.start(request)
                except Exception:
                    # The call may have launched before raising; leave the intent durable.
                    return self.status()
                active.update(stage="study", job=response["job"])
                with self._locked():
                    state = self._read()
                    state["active"] = active
                    self._write(state)
                return self.status()
            with self._locked():
                self._write(state)
            return self.status()

    def _advance(self, active):
        if active["stage"] in ("study_intent", "analysis_intent"):
            return self.status()
        state = None
        if active["stage"] == "study":
            job = self.workspace.job(active["job"])
            if job["status"] == "running":
                return self.status()
            if job["status"] == "complete" and (job.get("result") or {}).get("research_qualified"):
                active["stage"] = "analysis_intent"
                request = {"job": active["job"], "evidence_ids": active["evidence_ids"],
                           "rationale": "Scheduled bounded paper adaptation using current source evidence and paired replay.",
                           "apply": active["apply"]}
                active["analysis_request"] = request
                with self._locked():
                    state = self._read(); state["active"] = active; self._write(state)
                try:
                    workflow = self.workspace.analysis.start(request)
                except Exception:
                    return self.status()
                active.update(stage="analysis", workflow=workflow["id"])
            else:
                return self._finish(active, job["status"], job.get("error"))
        if active["stage"] == "analysis":
            workflow = self.workspace.analysis.job(active["workflow"])
            if workflow["status"] in ("queued", "running"):
                with self._locked():
                    state = self._read(); state["active"] = active; self._write(state)
                return self.status()
            if workflow["status"] == "unowned":
                return self.status()
            return self._finish(active, workflow["status"], workflow.get("error"))
        return self.status()

    def _finish(self, active, status, reason):
        with self._locked():
            state = self._read()
            config = state["config"]
            asset = active["asset"]
            prior = state["assets"].setdefault(asset, {})
            prior.update(status=status, reason=reason, last_job=active.get("job"),
                         last_workflow=active.get("workflow"), finished=time.time(),
                         last_attempt_cutoff=active["request"]["windows"]["holdout_end"],
                         next_due=time.time() + config["cadence_seconds"])
            if status == "no_candidate":
                prior["no_candidate_cutoff"] = active["request"]["windows"]["holdout_end"]
            state["active"] = None
            self._write(state)
        return self.status()

    def start(self):
        with self._mutex:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
            def run():
                while not self._stop.is_set():
                    try:
                        self.tick()
                    except Exception as ex:
                        with self._mutex, self._locked():
                            state = self._read()
                            state["last_error"] = {"type": type(ex).__name__, "at": time.time(),
                                                   "note": "Scheduler transition failed; active launch intents are retained."}
                            self._write(state)
                    self._stop.wait(5)
            self._thread = threading.Thread(target=run, name="adaptation-scheduler", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self, cancel=True):
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        with self._mutex, self._locked():
            active = self._read().get("active")
        if cancel and active and active.get("owner") == self._owner:
            if active["stage"] == "study":
                try:
                    self.workspace.cancel(active["job"])
                except ValueError:
                    pass  # A terminal study cannot be cancelled.
            elif active["stage"] == "analysis":
                self.workspace.analysis.journal.cancel(active["workflow"])
        return self.status()
