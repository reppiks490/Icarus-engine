from pathlib import Path

from icarus_engine.assets import resolve
from icarus_engine.runtime import AssetRunner, Journal, Portfolio, RunnerConfig
from icarus_engine.strategy.inputs import Inputs


class _Feed:
    def mintick(self, _ticker):
        return 0.25

    def ticker(self, _ticker):
        return 30000.0


def test_default_warmup_target_is_5000():
    assert RunnerConfig.__dataclass_fields__["warmup_bars"].default == 5000
    p = Portfolio(Journal(":memory:"), ".", warmup_bars=5000)
    assert p.warmup_bars == 5000


def test_nq_20m_prefers_bundled_archive_when_exact_history_missing(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    archive = data / "mnq_20m.csv"
    archive.write_text("ts,open,high,low,close,volume\n", encoding="utf-8")

    spec = resolve("NQ")
    spec.chart_tf = "20"
    r = AssetRunner(RunnerConfig(spec=spec, inputs=Inputs()), Journal(":memory:"), {"yahoo": _Feed()})
    r.base_dir = str(tmp_path)
    seen = []
    r._warmup_from_csv = lambda path, now: seen.append(path)  # type: ignore[method-assign]
    r.warmup(now_ts=1_800_000_000)

    assert seen == [str(archive)]
    assert r.warmup_source == "data/mnq_20m.csv"


def test_shipped_mnq_archive_has_deep_20m_history():
    path = Path("data/mnq_20m.csv")
    assert path.exists()
    # Header + more than 10k actual bars: this is a real depth assertion, not a UI counter.
    with path.open("r", encoding="utf-8") as fh:
        assert sum(1 for _ in fh) > 10_000


def test_dashboard_separates_warmup_bars_from_historical_trade_pieces():
    html = Path("icarus_engine/dashboard.html").read_text(encoding="utf-8")
    assert "Warm-up bars" in html
    assert "warmup_bars_loaded" in html
    assert "Hist. trades" in html
