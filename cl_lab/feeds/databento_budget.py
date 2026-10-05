# CL (Claude, Anthropic) — 2026-10-05 (rev. 2026-10-05 b) — owner's split of the remaining Databento credit across keys #1-#3
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
the schema or resolution.

Owner decision 2026-10-05 (b): whatever credit is left once everything else is paid for goes to MBO/MBP
order-book data. Each account has a SWEEP lane whose cap is not fixed: it is the account's estimated
remaining credit, minus a small reserve, minus everything committed to the account's other lanes. A
capped lane commits its full cap until it is marked finished, then only what it actually spent, so money
a history lane did not need flows to the sweep. The reserve pays for the never-ending daily top-ups of the
OHLCV corpus (recorded in the ``corpus:<account>`` ledgers, about $0.002 a day in total at three lab runs
a day) and absorbs rounding in the estimates; a corpus top-up is refused rather than let an account go
past its estimated credit."""
from __future__ import annotations

import json
import os
import time

LEDGER_DIR = "automation_intelligence/cl_lab/spend"

LANES = {
    # lane id                     account      lifetime cap   what it buys
    "history:ES":           dict(account="primary", cap_usd=25.0, what="ES ohlcv-1m 2010-06 -> 2024-09"),
    "depth:index":          dict(account="secondary", cap_usd=93.0, what="NQ/MNQ/ES/MES/RTY/M2K/YM/MYM MBO + MBP-10 days"),
    "history:NQ":           dict(account="third", cap_usd=25.0, what="NQ ohlcv-1m 2010-06 -> 2024-09"),
    "depth:diversifier":    dict(account="third", cap_usd=95.0, what="GC/MGC/SI/SIL/BTC/MBT/PL/PA/VX/VXM/ZN/DX depth days"),
}
ESTIMATED_REMAINING_USD = dict(primary=56.0, secondary=98.5, third=125.0)
RESERVE_USD = dict(primary=2.0, secondary=1.5, third=0.5)
SWEEP_LANES = {"depth:sweep:primary": "primary", "depth:sweep:secondary": "secondary", "depth:sweep:third": "third"}
CORPUS_LANES = {"corpus:primary": "primary", "corpus:secondary": "secondary"}


def check_split():
    """Raises if any account's fixed lane caps plus its reserve exceed its estimated remaining credit."""
    for acct, left in ESTIMATED_REMAINING_USD.items():
        total = sum(v["cap_usd"] for v in LANES.values() if v["account"] == acct) + RESERVE_USD.get(acct, 0.0)
        if total > left + 1e-9:
            raise ValueError(f"lane caps + reserve on {acct} total ${total:.2f} > remaining ${left:.2f}")


def account_of(lane: str) -> str:
    if lane in LANES:
        return LANES[lane]["account"]
    if lane in SWEEP_LANES:
        return SWEEP_LANES[lane]
    if lane in CORPUS_LANES:
        return CORPUS_LANES[lane]
    raise KeyError(lane)


def _spent(lane: str, ledger_dir: str, mirrors) -> tuple[float, bool]:
    """(lifetime spend, finished flag) of a lane: the copy with the larger spend wins."""
    copies = [c for c in (_load(_path(b, lane)) for b in [ledger_dir, *mirrors] if b) if c]
    if not copies:
        return 0.0, False
    best = max(copies, key=lambda c: c.get("spent_usd", 0.0))
    return float(best.get("spent_usd", 0.0)), bool(best.get("finished"))


def committed(lane: str, ledger_dir: str = LEDGER_DIR, mirrors=()) -> float:
    """What a lane holds of its account's credit: its full cap until it is finished, then its spend."""
    spent, finished = _spent(lane, ledger_dir, mirrors)
    if lane in LANES and not finished:
        return max(LANES[lane]["cap_usd"], spent)
    return spent


def headroom(account: str, ledger_dir: str = LEDGER_DIR, mirrors=(), *, exclude=()) -> float:
    """Estimated credit of ``account`` not yet spent or committed by any lane (``exclude`` left out)."""
    lanes = [l for l in (*LANES, *SWEEP_LANES, *CORPUS_LANES) if account_of(l) == account and l not in exclude]
    return ESTIMATED_REMAINING_USD.get(account, 0.0) - sum(committed(l, ledger_dir, mirrors) for l in lanes)


def sweep_cap(account: str, ledger_dir: str = LEDGER_DIR, mirrors=()) -> float:
    """Lifetime cap of the account's sweep lane (its own spend included)."""
    lane = next(l for l, a in SWEEP_LANES.items() if a == account)
    return max(0.0, headroom(account, ledger_dir, mirrors, exclude=(lane,)) - RESERVE_USD.get(account, 0.0))


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

    def __init__(self, lane: str, ledger_dir: str = LEDGER_DIR, mirror: str | None = None, mirrors=()):
        """``mirrors``: further directories holding copies of OTHER lanes' ledgers (used only to size a
        sweep lane's cap)."""
        acct = account_of(lane)
        if lane in LANES:
            cap = LANES[lane]["cap_usd"]
        elif lane in SWEEP_LANES:
            cap = sweep_cap(acct, ledger_dir, [m for m in (mirror, *mirrors) if m])
        else:                                   # corpus top-ups: whatever the account has not committed elsewhere
            cap = max(0.0, headroom(acct, ledger_dir, [m for m in (mirror, *mirrors) if m], exclude=(lane,)))
        self.lane, self.cfg = lane, dict(account=acct, cap_usd=round(cap, 6))
        self.paths = [_path(ledger_dir, lane)] + ([_path(mirror, lane)] if mirror else [])
        copies = [c for c in (_load(p) for p in self.paths) if c]
        self.data = max(copies, key=lambda c: c.get("spent_usd", 0.0)) if copies else dict(
            schema="cl_lab.databento_spend/1", lane=lane, account=acct, cap_usd=self.cfg["cap_usd"],
            spent_usd=0.0, entries=[])
        self.data["cap_usd"] = self.cfg["cap_usd"]

    @property
    def remaining(self) -> float:
        return max(0.0, self.cfg["cap_usd"] - float(self.data.get("spent_usd", 0.0)))

    def finish(self):
        """Mark the lane done: from now on it commits only what it spent (the rest flows to the sweep)."""
        if not self.data.get("finished"):
            self.data["finished"] = True
            self.save()

    def record(self, usd: float, what: str, at: str, log: bool = True):
        """``log=False`` updates the total without a ledger line (tiny OHLCV top-ups, to keep the file small)."""
        self.data["spent_usd"] = round(float(self.data.get("spent_usd", 0.0)) + float(usd), 6)
        if log:
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


TRANSIENT_STATUS = (502, 503, 504)


def refused(ex) -> bool:
    """True when the server answered with an HTTP error status: the request was refused, nothing was served."""
    st = getattr(ex, "http_status", None)
    return isinstance(st, int) and st >= 400


def paid_request(lane: "Lane", est: float, what: str, at: str, fn, attempts: int = 3, waits=(5.0, 20.0), log: bool = True):
    """Run a paid request with its estimate charged to ``lane`` BEFORE each attempt, so a run killed
    mid-download can never leave paid data off the ledger. The charge is refunded only when the server
    refused the attempt with an HTTP error status; only 502/503/504 refusals are retried. Anything else
    (timeouts, resets, a killed process) keeps the charge: bytes may have been served and billed."""
    for i in range(attempts):
        lane.record(est, what, at, log=log)
        try:
            return fn()
        except Exception as ex:  # noqa: BLE001 - classified below
            if refused(ex):
                lane.record(-est, f"{what} refunded: HTTP {ex.http_status}", at, log=log)
                if ex.http_status in TRANSIENT_STATUS and i < attempts - 1:
                    time.sleep(waits[min(i, len(waits) - 1)])
                    continue
            raise
