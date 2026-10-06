import json

import pytest

from cl_lab.data_fabric.orchestrator import (
    CatalogIntegrityError,
    build_gold_packet,
    load_intrinio_catalog,
    run_probe_cycle,
    summarize_access,
)


def test_summarize_access_accounts_for_every_row():
    out = summarize_access([
        {"access": "ACCESSIBLE"},
        {"access": "RESTRICTED"},
        {"access": "PROBE_UNRESOLVED"},
    ])
    assert out["total"] == 3
    assert out["accounted"] == 3
    assert out["counts"] == {"ACCESSIBLE": 1, "PROBE_UNRESOLVED": 1, "RESTRICTED": 1}
    assert out["integrity"] is True


def test_intrinio_catalog_loader_hashes_and_rejects_suspiciously_small_catalog():
    good = "\n".join([f"row{i}" for i in range(100)]).encode()

    def parser(_):
        return {"api_version": "2.x", "package_version": "7.x", "endpoint_count": 75}, list(range(75))

    meta, specs = load_intrinio_catalog(fetch_bytes=lambda _: good, parser=parser, min_endpoints=50)
    assert len(specs) == 75
    assert len(meta["catalog_sha256"]) == 64
    assert meta["source"]

    def tiny_parser(_):
        return {"endpoint_count": 2}, [1, 2]

    with pytest.raises(CatalogIntegrityError):
        load_intrinio_catalog(fetch_bytes=lambda _: b"tiny", parser=tiny_parser, min_endpoints=50)


def test_probe_cycle_isolates_provider_failure_and_handles_unconfigured(tmp_path):
    def intrinio_runner(secret):
        assert secret == "ik"
        return {"status": "ok", "catalog": {"sha256": "i"}, "rows": [{"access":"ACCESSIBLE"}]}

    def uw_runner(secret):
        assert secret == "uw"
        raise RuntimeError("provider exploded uw")

    result = run_probe_cycle(
        providers=("intrinio", "unusual_whales"),
        env={"INTRINIO_API_KEY": "ik", "UNUSUAL_WHALES_API_TOKEN": "uw"},
        output_dir=tmp_path,
        runners={"intrinio": intrinio_runner, "unusual_whales": uw_runner},
        now="2026-10-06T20:00:00Z",
    )
    assert result["providers"]["intrinio"]["status"] == "ok"
    assert result["providers"]["unusual_whales"]["status"] == "error"
    assert "provider exploded uw" not in json.dumps(result)
    assert (tmp_path / "manifests" / "latest.json").exists()
    assert (tmp_path / "gold" / "latest.json").exists()

    unconfigured = run_probe_cycle(
        providers=("intrinio", "unusual_whales"), env={}, output_dir=tmp_path / "b",
        runners={}, now="2026-10-06T20:00:00Z",
    )
    assert unconfigured["providers"]["intrinio"]["status"] == "unconfigured"
    assert unconfigured["providers"]["unusual_whales"]["status"] == "unconfigured"


def test_gold_packet_contains_only_compact_coverage_not_probe_rows():
    manifest = {
        "generated_at": "2026-10-06T20:00:00Z",
        "providers": {
            "x": {
                "status": "ok",
                "catalog": {"sha256": "abc"},
                "coverage": {"total": 2, "accounted": 2, "counts": {"ACCESSIBLE": 1, "RESTRICTED": 1}, "integrity": True},
                "rows": [{"access": "ACCESSIBLE", "huge": "secret-ish-row"}],
            }
        },
    }
    gold = build_gold_packet(manifest)
    assert gold["providers"]["x"]["coverage"]["total"] == 2
    assert "rows" not in gold["providers"]["x"]
    assert "secret-ish-row" not in json.dumps(gold)
