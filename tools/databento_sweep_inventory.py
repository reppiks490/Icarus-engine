"""Compare paid NQ sweep days with authenticated account-labelled vault entries."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ACCOUNTS = ("primary", "secondary", "third")


def inventory(vault: Path, ledgers: Path, now: datetime | None = None) -> dict:
    manifest = json.loads((vault / "manifest.json").read_text(encoding="utf-8"))
    sealed = manifest.get("caches", {}).get("sweep", {})
    accounts = {}
    for account in ACCOUNTS:
        ledger = json.loads((ledgers / f"depth__sweep__{account}.json").read_text(encoding="utf-8"))
        if ledger.get("account") != account:
            raise ValueError(f"sweep ledger account mismatch: {account}")
        paid = sorted(day for day, amount in ledger.get("days", {}).items()
                      if float(amount) > 1e-9)
        vaulted = []
        for day in paid:
            paths = (f"features/{account}/mbp10/nq/{day}.csv.gz",
                     f"resilience/{account}/nq/{day}.csv.gz")
            if all(path in sealed for path in paths):
                vaulted.append(day)
        missing = sorted(set(paid) - set(vaulted))
        accounts[account] = {
            "paid_days": len(paid),
            "vaulted_days": len(vaulted),
            "missing_days": missing,
            "ledger_recorded_usd": float(ledger.get("spent_usd", 0)),
        }
    gaps = sum(len(row["missing_days"]) for row in accounts.values())
    return {
        "schema": "icarus.databento_sweep_inventory/1",
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "status": "BLOCKED_MISSING_PAID_FEATURES" if gaps else "OK",
        "missing_paid_days": gaps,
        "accounts": accounts,
        "execution_authorized": False,
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=Path("data/depth_vault"))
    parser.add_argument("--ledgers", type=Path, default=Path("automation_intelligence/cl_lab/spend"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    if args.check:
        receipt = json.loads(args.check.read_text(encoding="utf-8"))
        print(f"Databento sweep durability: {receipt['status']}; missing paid days: {receipt['missing_paid_days']}")
        if receipt["status"] != "OK":
            raise SystemExit(1)
        return
    if not args.out:
        parser.error("--out is required unless --check is supplied")
    receipt = inventory(args.vault, args.ledgers)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Databento sweep inventory recorded: {receipt['status']}; missing paid days: {receipt['missing_paid_days']}")


if __name__ == "__main__":
    main()
