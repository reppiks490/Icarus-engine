"""Opt-in periodic public collection, with durable cross-process claims.

Public GET retries preserve immutable source revisions. This worker never calls
models or changes runner configuration. A one-hour claim lease exceeds the
collectors' bounded request budgets and prevents duplicate concurrent work.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .market_sources import SOURCES

MIN_INTERVAL = {"coinbase": 2, "cftc": 3600, "bls": 3600, "federal-reserve": 300,
                "bea": 300, "sec": 600, "yahoo-dxy": 900}
DEFAULT = {"enabled": False, "jobs": [
    {"source": s, "interval_seconds": 5 if s == "coinbase" else 3600, "options": {}}
    for s in SOURCES if s != "sec"]}


class SourceWatch:
    def __init__(self, sources):
        self.sources = sources
        self.path = Path(sources.root) / "source-watch.sqlite3"
        self._stop = threading.Event()
        self._thread = None
        self._mutex = threading.RLock()
        with self._db() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS configuration (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collections (
                    source TEXT PRIMARY KEY, next_due REAL NOT NULL, claim TEXT,
                    claimed_at REAL, finished_at REAL, result TEXT);
            """)

    @contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _config(con):
        row = con.execute("SELECT body FROM configuration WHERE id=1").fetchone()
        return json.loads(row[0]) if row else json.loads(json.dumps(DEFAULT))

    def configure(self, partial):
        if type(partial) is not dict or set(partial) - {"enabled", "jobs"}:
            raise ValueError("source watch accepts enabled and jobs only")
        with self._db() as con:
            config = {**self._config(con), **partial}
            if type(config["enabled"]) is not bool or type(config["jobs"]) is not list or len(config["jobs"]) > len(SOURCES):
                raise ValueError("invalid source watch configuration")
            seen = set()
            for job in config["jobs"]:
                if type(job) is not dict or set(job) != {"source", "interval_seconds", "options"}:
                    raise ValueError("each collection requires source, interval_seconds and options")
                source, interval = job["source"], job["interval_seconds"]
                if type(source) is not str or source not in SOURCES or source in seen:
                    raise ValueError("unknown or repeated source")
                seen.add(source)
                if type(interval) is not int or not MIN_INTERVAL[source] <= interval <= 604800:
                    raise ValueError("source cadence outside bounded limits")
                if type(job["options"]) is not dict or len(json.dumps(job["options"], allow_nan=False)) > 8192:
                    raise ValueError("source options must be a bounded object")
            con.execute("INSERT INTO configuration VALUES (1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                        (json.dumps(config, allow_nan=False),))
        return self.status()

    def status(self):
        with self._db() as con:
            config = self._config(con)
            rows = [dict(row) for row in con.execute("SELECT * FROM collections ORDER BY source")]
        for row in rows:
            row["result"] = json.loads(row["result"]) if row["result"] else None
            row["status"] = "collecting" if row["claim"] and row["claimed_at"] + 3600 > time.time() else "retry_due" if row["claim"] else "waiting"
        return {"config": config, "collections": rows, "running": bool(self._thread and self._thread.is_alive()),
                "minimum_intervals": MIN_INTERVAL, "models_called": False}

    def tick(self):
        now = time.time()
        with self._db() as con:
            config = self._config(con)
            if not config["enabled"]:
                return None
            due = []
            for job in config["jobs"]:
                row = con.execute("SELECT * FROM collections WHERE source=?", (job["source"],)).fetchone()
                if row and (row["next_due"] > now or (row["claim"] and row["claimed_at"] + 3600 > now)):
                    continue
                due.append((row["next_due"] if row else 0, job))
            if not due:
                return None
            _, job = min(due, key=lambda item: item[0])
            claim = uuid.uuid4().hex
            con.execute("INSERT INTO collections(source,next_due,claim,claimed_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(source) DO UPDATE SET next_due=excluded.next_due,claim=excluded.claim,claimed_at=excluded.claimed_at",
                        (job["source"], now + job["interval_seconds"], claim, now))
        try:
            result = self.sources.collect(job["source"], job["options"])
        except Exception as ex:
            result = {"status": "error", "error": type(ex).__name__ + ": collection failed"}
        with self._db() as con:
            con.execute("UPDATE collections SET claim=NULL,finished_at=?,result=? WHERE source=? AND claim=?",
                        (time.time(), json.dumps(result, allow_nan=False), job["source"], claim))
        return result

    def start(self):
        with self._mutex:
            if self._thread and self._thread.is_alive():
                self._stop.clear()
                return self.status()
            self._stop.clear()
            def run():
                while not self._stop.is_set():
                    self.tick()
                    self._stop.wait(1)
            self._thread = threading.Thread(target=run, name="public-source-watch", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        return self.status()
