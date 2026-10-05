# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.events: verified event calendars for the cl-r2 hypotheses
"""Scheduled FOMC decision dates, 2024–2026, checked against the Federal Reserve's
published meeting calendars (federalreserve.gov/monetarypolicy/fomccalendars.htm). Every
meeting listed is two days; the first day is the previous business day; each had a
press conference. The 2025-08-22 notation vote is not a meeting and is excluded."""
from __future__ import annotations

from datetime import date, timedelta

FOMC_DECISIONS = (
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12),
    date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18),
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7), date(2025, 6, 18),
    date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10),
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
)
EXCLUDED = (date(2025, 8, 22),)
FOMC_SOURCE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def fomc_events():
    out = []
    for d in FOMC_DECISIONS:
        first = d - timedelta(days=1)
        assert first.weekday() < 5 and d.weekday() < 5
        out.append(dict(decision=d, first_day=first, press_conference=True))
    return out


def month_ends(dates) -> list[dict]:
    """For a sorted sequence of trading dates: per month, its last date T, the prior month's last
    date M0 and the positions of both (months without a prior month in the data are skipped)."""
    dates = list(dates)
    ends = [i for i in range(len(dates) - 1)          # the trailing, possibly unfinished month is never an end
            if (dates[i + 1].year, dates[i + 1].month) != (dates[i].year, dates[i].month)]
    out = []
    for a, b in zip(ends[:-1], ends[1:]):
        out.append(dict(month=f"{dates[b].year}-{dates[b].month:02d}", m0=a, t=b))
    return out
