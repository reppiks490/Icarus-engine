# Agent roadmap

The agent system that turns collected data into tested, forward-proven setups. Design agreed with the
owner on 2026-10-11. Status is updated as each agent lands; `ICARUS_STATE.md` §7 points here.

Every agent writes its results to a file in the repository, never only to a chat. An agent that produces
nothing for three runs disables itself and says why. No agent can place a trade.

## Status

| Id | Agent | Purpose | Runs on | Status |
|---|---|---|---|---|
| R2 | Single source of truth | `ICARUS_STATE.md` read first by every AI | — | Done |
| X1 | Claude ↔ ChatGPT coordination | Task lists and inboxes in `coordination/`; coordinator answers twice a day | Claude routine | Building |
| S1 | Data-health sentinel | Every source: key present, last success, rows, failures; vault and budgets | GitHub Actions, every 3 h | Done |
| C8 | Daily briefing | One phone-readable report: data health, agent activity, candidates and verdicts | Claude routine, daily | Done |
| R1 | Claims referee | Ledger of every AI claim, verified against repo and CI | Claude routine | Planned |
| I1 | Red team | Look-ahead, Heikin-Ashi fills, roll jumps, cost stress on every claimed result | On demand | Planned |
| C2 | Win-rate frontier | WR vs expectancy across TP/SL/time-stop for each setup | Actions | Planned (hard: test design) |
| C4 | Regime cartographer | Ex-ante regime labels; which rules are "on" today | Actions | Planned (hard: leakage) |
| I2 | Fragility scanner | 1,000 small perturbations per setup | Actions | Planned |
| P1 | Shadow trader | Forward-only paper trades with real costs | Actions, daily | Planned |
| C3 | Meta-labeler | Take/skip model on the Icarus entry | Actions | Planned (hard: test design) |
| D1 | Order-flow test | Failed sweep vs book refill; book imbalance | Actions, after each vault seal | Pre-registered, waiting for 20 days |
| A1 | Liquidation hunter | Hyperliquid liquidation clusters as visible stop pools | Claude routine (Coinversa) | Planned |
| B1 | Options pressure | Dealer gamma levels from QQQ chains | Actions (Alpha Vantage key) | Planned |

"Hard" marks steps where the owner raises the effort setting before the work starts.
