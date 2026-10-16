import json
from datetime import datetime, timezone

import pytest

from tools.databento_sweep_inventory import inventory, main


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def test_account_ledger_days_are_not_mistaken_for_vaulted_features(tmp_path):
    vault, ledgers = tmp_path / "vault", tmp_path / "ledgers"
    _write(vault / "manifest.json", {"caches": {"sweep": {
        "features/primary/mbp10/nq/2026-10-01.csv.gz": {},
        "resilience/primary/nq/2026-10-01.csv.gz": {},
        "features/secondary/mbp10/nq/2026-10-03.csv.gz": {},
        "resilience/secondary/nq/2026-10-03.csv.gz": {},
    }}})
    for account, days in (("primary", {"2026-10-01": 1.0, "2026-10-02": 2.0}),
                          ("secondary", {"2026-10-03": 3.0}), ("third", {})):
        _write(ledgers / f"depth__sweep__{account}.json",
               {"account": account, "days": days, "spent_usd": sum(days.values())})

    receipt = inventory(vault, ledgers, datetime(2026, 10, 16, tzinfo=timezone.utc))
    assert receipt["missing_paid_days"] == 1
    assert receipt["accounts"]["primary"]["paid_days"] == 2
    assert receipt["accounts"]["primary"]["vaulted_days"] == 1
    assert receipt["accounts"]["primary"]["missing_days"] == ["2026-10-02"]
    assert receipt["accounts"]["secondary"]["vaulted_days"] == 1
    assert receipt["accounts"]["third"]["paid_days"] == 0
    out = tmp_path / "receipt.json"
    _write(out, receipt)
    with pytest.raises(SystemExit, match="1"):
        main(["--check", str(out)])

    manifest = json.loads((vault / "manifest.json").read_text())
    manifest["caches"]["sweep"]["features/primary/mbp10/nq/2026-10-02.csv.gz"] = {}
    manifest["caches"]["sweep"]["resilience/primary/nq/2026-10-02.csv.gz"] = {}
    _write(vault / "manifest.json", manifest)
    assert inventory(vault, ledgers)["status"] == "OK"
