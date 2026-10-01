"""Persistent, provenance-preserving raw bar cache for ICARUS warm-up/replay.

The cache stores market observations only. It never serializes strategy, order,
position, broker-emulator or execution state.
"""
from __future__ import annotations
import os, sqlite3, threading, time
from typing import Iterable, List
from .pine.timeframe import Bar

class BarCache:
    def __init__(self,path:str):
        self.path=os.path.realpath(path)
        os.makedirs(os.path.dirname(self.path),exist_ok=True)
        self._lock=threading.RLock()
        self.con=sqlite3.connect(self.path,check_same_thread=False,timeout=30)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.execute("""CREATE TABLE IF NOT EXISTS bars(
            asset TEXT NOT NULL,
            sub_minutes INTEGER NOT NULL,
            ts INTEGER NOT NULL,
            o REAL NOT NULL,h REAL NOT NULL,l REAL NOT NULL,c REAL NOT NULL,v REAL NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            retrieved_at INTEGER NOT NULL,
            PRIMARY KEY(asset,sub_minutes,ts)
        )""")
        self.con.execute("CREATE INDEX IF NOT EXISTS bars_asset_ts ON bars(asset,ts)")
        self.con.commit()

    def put_many(self,asset:str,sub_minutes:int,bars:Iterable[Bar],source:str="")->int:
        rows=[(str(asset).upper(),int(sub_minutes),int(b.ts),float(b.o),float(b.h),float(b.l),float(b.c),float(b.v),
               str(source)[:120],int(time.time())) for b in bars]
        if not rows: return 0
        with self._lock:
            self.con.executemany("""INSERT INTO bars(asset,sub_minutes,ts,o,h,l,c,v,source,retrieved_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(asset,sub_minutes,ts) DO UPDATE SET
                  o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,v=excluded.v,
                  source=excluded.source,retrieved_at=excluded.retrieved_at""",rows)
            self.con.commit()
        return len(rows)

    def load(self,asset:str,sub_minutes:int,start_ts:int,end_ts:int,limit:int=500000)->List[Bar]:
        limit=max(1,min(int(limit),1000000))
        with self._lock:
            rows=self.con.execute("""SELECT ts,o,h,l,c,v FROM bars
                WHERE asset=? AND sub_minutes=? AND ts>=? AND ts<=?
                ORDER BY ts LIMIT ?""",(str(asset).upper(),int(sub_minutes),int(start_ts),int(end_ts),limit)).fetchall()
        return [Bar(int(t),float(o),float(h),float(l),float(c),float(v)) for t,o,h,l,c,v in rows]

    def stats(self,asset:str):
        with self._lock:
            rows=self.con.execute("""SELECT sub_minutes,COUNT(*),MIN(ts),MAX(ts),MAX(retrieved_at)
                FROM bars WHERE asset=? GROUP BY sub_minutes ORDER BY sub_minutes""",(str(asset).upper(),)).fetchall()
        return {"asset":str(asset).upper(),
                "series":[{"sub_minutes":int(m),"bars":int(n),"first_ts":a,"last_ts":b,"last_retrieved_at":r}
                          for m,n,a,b,r in rows],
                "stores_execution_state":False,"execution_authorized":False}

    def prune_before(self,cutoff_ts:int)->int:
        with self._lock:
            before=self.con.total_changes
            self.con.execute("DELETE FROM bars WHERE ts < ?",(int(cutoff_ts),))
            self.con.commit()
            return self.con.total_changes-before

    def close(self):
        with self._lock:
            try: self.con.close()
            except Exception: pass

def merge_bars(cached, fresh):
    """Chronological dedupe with fresh provider observations winning on timestamp."""
    rows={int(b.ts):b for b in cached}
    for b in fresh: rows[int(b.ts)]=b
    return [rows[k] for k in sorted(rows)]
