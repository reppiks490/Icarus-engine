# Running Icarus where it actually runs

This repository was developed in a Claude Code cloud container that **cannot
reach any live data feed**. Every host `icarus_engine/runtime.py` needs is
denied by that environment's network policy:

```
query1.finance.yahoo.com   live feed, equities + futures   BLOCKED (403)
api.coinbase.com           live feed, crypto               BLOCKED (403)
api.kraken.com             live feed, crypto               BLOCKED (403)
```

So the research here is real and the live engine has never been exercised from
that container. On a normal machine with ordinary internet access, it runs.

## Getting everything

```bash
git clone https://github.com/reppiks490/Icarus-engine.git
cd Icarus-engine
git checkout claude/verification-conversation-ebkh15
python -m pytest tests tests_engine --import-mode=importlib -q
```

`--import-mode=importlib` is required: `tests/` and `tests_engine/` share module
basenames and collection aborts without it.

## What comes with it

| path | what it is |
|---|---|
| `icarus_engine/` | Astra's engine -- the paper-trading system and Pine twin |
| `icarus/` | the second engine. **Loses money on real data on both spans.** Kept for its feature layers, not as a strategy |
| `data/mnq_*m_full.csv` | two years of real continuous MNQ, 5/10/20/30m, front-month spliced at the roll |
| `tools/` | the research instruments: metrics, goal, duration, premise, capture, range bars, cross-asset |
| `research/scripts/` | the one-off scripts behind every number in the log |
| `research/results/` | their raw outputs, so a claim can be traced to the run |
| `docs/RESEARCH_LOG.md` | **read this first** -- every finding, including the negative ones |
| `presets/` | loadable configs. NQ-20m-ultracoded and NQ-10m-original are RECONSTRUCTED from what the tests pin; replace with your real exports |

## Live paper trading

```bash
python -m icarus_engine.cli run --port 8791
```

Dashboard at `http://127.0.0.1:8791/`. It prints an admin token on startup.
`--warmup` replays history before going live; `--roll volume` uses
TradingView's `1!` contract rule for NQ/ES/YM.

This is the only execution path that counts. A research result is only real if
it can be written as `presets/<name>.json` and run here.

## Backtesting against the real tape

```bash
python tools/real_mnq.py 20          # both engines, TUNE vs HOLD, 20m
python tools/run_capture.py          # can the LTF capture the HTF move
python tools/run_premise.py          # does the sweep premise hold, 10 markets
```

The train/holdout split is **2025-10-01**. Everything before is for tuning;
everything after has to be left alone or it stops being held out.

## The rules that produced the log

Learned the expensive way, each one after a false positive got through:

1. **Never trust the synthetic tape.** Four results inverted on real data --
   the 83.6% win rate, the location sign, the hold-time gradient, the
   cross-asset features.
2. **Two spans, always.** A result on one span is a curve fit with a date.
3. **Match, then stratify.** A biased control defeats every downstream gate;
   FDR control cannot see one. See trap 8.
4. **Positive controls both ways.** Prove drift is removed AND that a planted
   effect survives. A control that erases everything is as useless as one that
   erases nothing.
5. **Never rank by a statistic computed on the trade's own survival.**
   Duration, MFE, MAE and bars-to-target are outcome-conditioned; slicing by
   them always produces a gradient. See F-003.
6. **Bars are not durations.** 30 bars is 2.5h at 5m and 10h at 20m.
7. **A permutation null before belief.** The headline +$14,487 fails at
   p=0.377.
