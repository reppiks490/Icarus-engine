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
        self.con.execute("""CREATE TABLE IF NOT EXISTS revisions(
            id INTEGER PRIMARY KEY,
            asset TEXT NOT NULL, sub_minutes INTEGER NOT NULL, ts INTEGER NOT NULL,
            old_o REAL,old_h REAL,old_l REAL,old_c REAL,old_v REAL,
            new_o REAL,new_h REAL,new_l REAL,new_c REAL,new_v REAL,
            old_source TEXT NOT NULL DEFAULT '', new_source TEXT NOT NULL DEFAULT '',
            price_changed INTEGER NOT NULL, volume_changed INTEGER NOT NULL,
            observed_at INTEGER NOT NULL
        )""")
        self.con.execute("CREATE INDEX IF NOT EXISTS revisions_asset_ts ON revisions(asset,ts)")
        self.con.commit()

    def put_many(self,asset:str,sub_minutes:int,bars:Iterable[Bar],source:str="")->int:
        asset=str(asset).upper(); sub_minutes=int(sub_minutes); source=str(source)[:120]; now=int(time.time())
        rows=[(asset,sub_minutes,int(b.ts),float(b.o),float(b.h),float(b.l),float(b.c),float(b.v),source,now) for b in bars]
        if not rows: return 0
        with self._lock:
            existing={}
            timestamps=[r[2] for r in rows]
            for k in range(0,len(timestamps),500):
                chunk=timestamps[k:k+500]
                qs=",".join("?" for _ in chunk)
                q=f"""SELECT ts,o,h,l,c,v,source FROM bars
                    WHERE asset=? AND sub_minutes=? AND ts IN ({qs})"""
                for old in self.con.execute(q,(asset,sub_minutes,*chunk)).fetchall():
                    existing[int(old[0])]=old
            revisions=[]
            for row in rows:
                _,_,ts,o,h,l,cl,v,new_source,observed=row
                old=existing.get(ts)
                if old is None: continue
                _,oo,oh,ol,oc,ov,old_source=old
                price_changed=int(any(abs(float(a)-float(b))>1e-12 for a,b in ((oo,o),(oh,h),(ol,l),(oc,cl))))
                volume_changed=int(abs(float(ov)-float(v))>1e-9)
                if price_changed or volume_changed:
                    revisions.append((asset,sub_minutes,ts,oo,oh,ol,oc,ov,o,h,l,cl,v,
                                      str(old_source or "")[:120],new_source,price_changed,volume_changed,observed))
            if revisions:
                self.con.executemany("""INSERT INTO revisions(
                    asset,sub_minutes,ts,old_o,old_h,old_l,old_c,old_v,new_o,new_h,new_l,new_c,new_v,
                    old_source,new_source,price_changed,volume_changed,observed_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",revisions)
            self.con.executemany("""INSERT INTO bars(asset,sub_minutes,ts,o,h,l,c,v,source,retrieved_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(asset,sub_minutes,ts) DO UPDATE SET
                  o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,v=excluded.v,
                  source=excluded.source,retrieved_at=excluded.retrieved_at
                WHERE bars.source=excluded.source OR bars.source='' OR excluded.source=''""",rows)
            self.con.commit()
        return len(rows)

    def load(self,asset:str,sub_minutes:int,start_ts:int,end_ts:int,limit:int=500000)->List[Bar]:
        limit=max(1,min(int(limit),1000000))
        with self._lock:
            rows=self.con.execute("""SELECT ts,o,h,l,c,v FROM bars
                WHERE asset=? AND sub_minutes=? AND ts>=? AND ts<=?
                ORDER BY ts LIMIT ?""",(str(asset).upper(),int(sub_minutes),int(start_ts),int(end_ts),limit)).fetchall()
        return [Bar(int(t),float(o),float(h),float(l),float(c),float(v)) for t,o,h,l,c,v in rows]

    def load_records(self,asset:str,sub_minutes:int,start_ts:int,end_ts:int,limit:int=500000):
        """Load cached bars with source identity so roll boundaries are not overwritten in memory."""
        limit=max(1,min(int(limit),1000000))
        with self._lock:
            rows=self.con.execute("""SELECT ts,o,h,l,c,v,source FROM bars
                WHERE asset=? AND sub_minutes=? AND ts>=? AND ts<=?
                ORDER BY ts LIMIT ?""",(str(asset).upper(),int(sub_minutes),int(start_ts),int(end_ts),limit)).fetchall()
        return [{"bar":Bar(int(t),float(o),float(h),float(l),float(c),float(v)),"source":str(src or "")}
                for t,o,h,l,c,v,src in rows]

    def stats(self,asset:str):
        asset=str(asset).upper()
        with self._lock:
            rows=self.con.execute("""SELECT sub_minutes,COUNT(*),MIN(ts),MAX(ts),MAX(retrieved_at)
                FROM bars WHERE asset=? GROUP BY sub_minutes ORDER BY sub_minutes""",(asset,)).fetchall()
            rev=self.con.execute("""SELECT COUNT(*),COALESCE(SUM(price_changed),0),COALESCE(SUM(volume_changed),0),MAX(observed_at)
                FROM revisions WHERE asset=?""",(asset,)).fetchone()
        return {"asset":asset,
                "series":[{"sub_minutes":int(m),"bars":int(n),"first_ts":a,"last_ts":b,"last_retrieved_at":r}
                          for m,n,a,b,r in rows],
                "revisions":{"total":int(rev[0] or 0),"price":int(rev[1] or 0),"volume":int(rev[2] or 0),"last_at":rev[3]},
                "stores_execution_state":False,"execution_authorized":False}

    def recent_revisions(self,asset:str,limit:int=20):
        limit=max(1,min(int(limit),200))
        with self._lock:
            rows=self.con.execute("""SELECT sub_minutes,ts,old_c,new_c,old_v,new_v,old_source,new_source,
                price_changed,volume_changed,observed_at FROM revisions WHERE asset=?
                ORDER BY id DESC LIMIT ?""",(str(asset).upper(),limit)).fetchall()
        return [{"sub_minutes":int(m),"ts":int(ts),"old_close":oc,"new_close":nc,"old_volume":ov,"new_volume":nv,
                 "old_source":osrc,"new_source":nsrc,"price_changed":bool(pc),"volume_changed":bool(vc),"observed_at":at}
                for m,ts,oc,nc,ov,nv,osrc,nsrc,pc,vc,at in rows]

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


def merge_source_aware(cached_records, fresh, fresh_source:str):
    """Merge while protecting a cached futures roll segment from another contract.

    A fresh observation may replace a cached timestamp only when source identity
    matches (or one side is unlabelled). This prevents a current contract's
    historical fetch from rewriting timestamps that were actually observed from
    the prior active contract before a roll.
    """
    rows={int(r["bar"].ts):(r["bar"],str(r.get("source") or "")) for r in cached_records}
    src=str(fresh_source or "")
    protected=0
    for b in fresh:
        old=rows.get(int(b.ts))
        if old is not None and old[1] and src and old[1]!=src:
            protected+=1
            continue
        rows[int(b.ts)]=(b,src)
    return [rows[k][0] for k in sorted(rows)],protected
