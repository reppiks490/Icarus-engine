from pathlib import Path
from icarus_engine.bar_cache import BarCache, merge_bars
from icarus_engine.pine.timeframe import Bar


def test_bar_cache_roundtrip_and_fresh_overwrite(tmp_path):
    p=tmp_path/"state"/"cache"/"bars.sqlite3"
    c=BarCache(str(p))
    a=Bar(100,1,2,.5,1.5,10)
    c.put_many("NQ",1,[a],source="old")
    got=c.load("NQ",1,0,200)
    assert len(got)==1 and got[0].c==1.5
    b=Bar(100,1,3,.5,2.5,11)
    c.put_many("NQ",1,[b],source="fresh")
    got=c.load("NQ",1,0,200)
    assert got[0].c==2.5
    s=c.stats("NQ")
    assert s["series"][0]["bars"]==1
    assert s["stores_execution_state"] is False
    assert s["execution_authorized"] is False


def test_merge_bars_is_chronological_and_fresh_wins():
    cached=[Bar(100,1,2,1,1.5,1),Bar(200,2,3,2,2.5,1)]
    fresh=[Bar(200,2,4,2,3.5,2),Bar(300,3,4,3,3.5,1)]
    out=merge_bars(cached,fresh)
    assert [b.ts for b in out]==[100,200,300]
    assert out[1].c==3.5


def test_runtime_wires_persistent_cache_without_execution_state():
    text=Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    assert "BarCache" in text and "merge_bars" in text
    assert '"persistent_bar_cache"' in text
    assert "highwater = max(self.last_sub_ts or -1, self.last_raw_sub_ts or -1)" in text
    mod=Path("icarus_engine/bar_cache.py").read_text(encoding="utf-8")
    for forbidden in (".entry(", ".exit(", ".close(", "PendingEntry", "ExitOrder"):
        assert forbidden not in mod
