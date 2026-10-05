# CL (Claude, Anthropic) — 2026-10-05 — owner's split of the remaining Databento credit across keys #1-#3
"""Every paid lane has a lifetime cap on one account, and the caps of an account never add up to more
than that account's estimated remaining credit. Each lane writes only its own ledger file
(``automation_intelligence/cl_lab/spend/<lane>.json``, committed, mirrored in the workflow's cache), so
two workflows can never overspend an account by racing each other.

Remaining credit per account was estimated on 2026-10-05 from the committed feed manifests, assuming
Databento's $125 sign-up credit per account (the portal is the authority; correct the numbers here if
it differs):
- key #1 (primary): about $69 spent on the 25-month OHLCV corpus for ~33 feeds, so ~$56 left;
- key #2 (secondary): $26.46 on 15 months of VXM + DX bars, so ~$98.5 left;
- key #3 (third): nothing spent, so $125 left.
Ongoing daily top-ups of the key #1/#2 corpora (~2 cents a day in total) are not capped here; the
margins below absorb them for years.

A lane that cannot afford all of its data shortens the date range (oldest data first) and never changes
the schema or resolution."""
from __future__ import annotations

import json
import os

LEDGER_DIR = "automation_intelligence/cl_lab/spend"

LANES = {
    # lane id                     account      lifetime cap   what it buys
    "history:ES":           dict(account="primary", cap_usd=25.0, what="ES ohlcv-1m 2010-06 -> 2024-09"),
    "depth:index":          dict(account="secondary", cap_usd=93.0, what="NQ/MNQ/ES/MES/RTY/M2K/YM/MYM MBO + MBP-10 days"),
    "history:NQ":           dict(account="third", cap_usd=25.0, what="NQ ohlcv-1m 2010-06 -> 2024-09"),
    "depth:diversifier":    dict(account="third", cap_usd=95.0, what="GC/MGC/SI/SIL/BTC/MBT/PL/PA/VX/VXM/ZN/DX depth days"),
}
ESTIMATED_REMAINING_USD = dict(primary=56.0, secondary=98.5, third=125.0)


def check_split():
    """Raises if any account's lane caps exceed its estimated remaining credit."""
    for acct, left in ESTIMATED_REMAINING_USD.items():
        total = sum(v["cap_usd"] for v in LANES.values() if v["account"] == acct)
        if total > left + 1e-9:
            raise ValueError(f"lane caps on {acct} total ${total:.2f} > remaining ${left:.2f}")


def _path(base, lane):
    return os.path.join(base, lane.replace(":", "__") + ".json")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Lane:
    """Lifetime spend ledger of one lane. ``mirror`` is a cache directory holding a second copy; the
    copy with the larger spend wins, so a run that died before committing cannot reset the budget."""

    def __init__(self, lane: str, ledger_dir: str = LEDGER_DIR, mirror: str | None = None):
        if lane not in LANES:
            raise KeyError(lane)
        self.lane, self.cfg = lane, LANES[lane]
        self.paths = [_path(ledger_dir, lane)] + ([_path(mirror, lane)] if mirror else [])
        copies = [c for c in (_load(p) for p in self.paths) if c]
        self.data = max(copies, key=lambda c: c.get("spent_usd", 0.0)) if copies else dict(
            schema="cl_lab.databento_spend/1", lane=lane, account=self.cfg["account"], cap_usd=self.cfg["cap_usd"],
            spent_usd=0.0, entries=[])
        self.data["cap_usd"] = self.cfg["cap_usd"]

    @property
    def remaining(self) -> float:
        return max(0.0, self.cfg["cap_usd"] - float(self.data.get("spent_usd", 0.0)))

    def record(self, usd: float, what: str, at: str):
        self.data["spent_usd"] = round(float(self.data.get("spent_usd", 0.0)) + float(usd), 6)
        self.data["entries"] = (self.data.get("entries") or [])[-499:] + [dict(usd=round(float(usd), 6), what=what, at=at)]
        self.save()

    def save(self):
        self.data["execution_authorized"] = False
        for p in self.paths:
            os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1, sort_keys=True)
                f.write("\n")
            os.replace(tmp, p)
