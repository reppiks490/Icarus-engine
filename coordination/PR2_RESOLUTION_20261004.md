# PR #2 (`claude/research-restore`) — resolution

CL (Claude, Anthropic) — 2026-10-04. Verdict: **RECONCILE UNIQUE WORK, then FORMALLY RETIRE AS SUPERSEDED.**

Evidence, comparing the PR head with its merge base (2026-09-19) and current `main` (233 files changed by the PR):

| Class | Files | Evidence |
|---|---|---|
| Already on main, byte-identical | 208 | same blob SHA on `main` |
| Absorbed by main, then evolved | 7 (`tests.yml`, `.gitignore`, `backtest.py`, `cli.py`, `dashboard.html`, `research_service.py`, `runtime.py`, `server.py`) | the PR's exact blob appears in main's history (commit `a491ca62`), and main has moved past it |
| Unique research text | `docs/RESEARCH_LOG.md` sections F-004 (closed), N-004, N-005, N-003 (confirmed) | 135 non-blank lines found nowhere in main's log → **ported verbatim** in this PR with provenance |
| Unique tool variant | `tools/asset_panel.py` | the PR variant reads committed `data/panel/*.csv`; main's variant reads the API spill path. It has no use without the panel CSVs below, so it is not ported |
| Withheld | `data/panel/*.csv` (13 ETF 5m panels) + `_verified_tickers.json` | raw vendor bars; redistributing them in a public repository is a licensing risk. They stay on the branch |
| Trivial | `README.md` | one title line |

The branch is preserved (not deleted, not force-pushed). Once this reconciliation merges, PR #2 can be closed as superseded with a link here. PR #2 no longer blocks anything.
