# ICARUS Real-Price Shadow Twin — Design

**Date:** 2026-10-14  
**Task:** RT01  
**Status:** Design / no execution authority  
**Repository:** `reppiks490/Icarus-engine`  
**Design branch:** `chatgpt/real-price-shadow-twin-spec-20261014`

## 1. Purpose

The owner is currently running ICARUS with Heikin-Ashi as both the strategy chart representation and the primary replay/fill representation. The primary HA run is useful as a signal/reference stream, but synthetic HA fill prices are not executable market evidence.

Build a second, strictly paper-only execution twin that consumes **the exact same strategy/order-intent stream** produced by the existing HA ICARUS strategy while evaluating fills and path-dependent outcomes on the corresponding **standard real-price bars**.

The twin answers one narrow empirical question:

> When ICARUS makes the same decision at the same time with the same direction and size, how much of the HA result survives when the order is evaluated against real-price bars?

The system must quantify that answer trade-for-trade without changing the HA strategy, its decisions, its sizing, or its primary results.

## 2. Repository constraints and truth model

This design obeys `ICARUS_STATE.md`:

- no setup is claimed proven by this feature;
- real-price fills are the only execution evidence;
- HA fills remain artifact/reference results;
- the twin is observation/research only and cannot authorize execution;
- no spend, credentials, scheduler changes, or broker activation are introduced;
- current CL research, Claude P1 shadow-trader work, and automation lanes are out of scope.

The existing asset contract already separates `chart_type` from `fill_on`. The canonical runtime also already has both the transformed chart bar and the underlying real bar available in the chart-bar path. Existing `icarus_bridge` shadow/reality-gap code is useful precedent, but RT01 must not route through a broker or bridge; it lives beside the local engine emulator and has no external order handle.

## 3. Success criteria

RT01 is successful only if all of the following are true:

1. Turning the twin on does not change any primary ICARUS decision, order intent, fill, trade, state field, or P&L.
2. Every primary order mutation that is eligible for mirroring is assigned a deterministic twin sequence and offered to the real-price emulator in the same order.
3. The twin processes only standard real-price bars with timestamps identical to the corresponding primary chart bar.
4. The twin can legitimately disagree with the primary on whether an order fills, whether a stop/target is touched, exit timing, P&L, MAE/MFE, or whether a later mirrored order has anything to act on.
5. Shadow disagreement never feeds back into the strategy.
6. Warm-up/replay and post-go-live results are partitioned and reported separately.
7. Metrics expose fill parity, outcome agreement, real-price win rate, P&L realization, drawdown, and price deltas without relabeling HA P&L as executable.
8. The entire lane is structurally incapable of sending a live/paper broker order.
9. Replay is deterministic: identical bars + configuration produce identical twin evidence.
10. Missing or invalid real-price bars fail the twin closed while leaving the primary engine untouched.

## 4. Approaches considered

### A. Run a second complete strategy instance with `chart_type=heikin_ashi, fill_on=real`

Rejected for this specific experiment. It is useful as a separate strategy test, but once real fills alter position state, closed-trade history, time-of-day outcome tracking, or other state read by the strategy, the second strategy instance can begin making different decisions. It would no longer answer the owner's requested question: *the same trade at the same time, but at real prices*.

### B. Re-price primary closed trades after the fact

Rejected. Post-hoc entry/exit repricing cannot correctly determine path-dependent stop/target ordering, missed limit entries, gap-through behavior, dynamic trails, reversals, or partial exits.

### C. Mirror one strategy's order-intent stream into two emulators

**Chosen.** The existing strategy runs exactly once and reads only its primary emulator state. A mirror wrapper duplicates order mutations into an isolated real-price emulator while all reads/properties exposed to the strategy continue to come exclusively from the primary emulator.

This is the only design that simultaneously preserves exact strategy decisions and allows real-price path differences to emerge honestly.

## 5. Core architecture

### 5.1 New module

Create `icarus_engine/shadow_twin.py` with two principal components:

- `MirroredEmulator`: emulator-compatible facade used by `PulseStrategy` and runtime;
- `ShadowTwinEvidence`: deterministic matcher/metrics accumulator over primary and real-price shadow events.

`MirroredEmulator` owns:

- `primary`: the existing canonical `Emulator`;
- `shadow`: a second `Emulator` configured with the same capital, commission, mintick, multiplier, pyramiding, and slippage settings unless an explicit shadow-only stress override is supplied;
- `evidence`: `ShadowTwinEvidence`;
- the real bar paired with the current primary bar;
- a monotonic `intent_seq` used to match mirrored operations.

### 5.2 Authority boundary

All strategy-visible reads resolve to `primary` only, including:

- `position_size`;
- `open`, `closed`, and `fills`;
- `netprofit` and `equity`;
- `qty_open()`;
- any private/pending structures already read by canonical runtime diagnostics.

The shadow emulator is write-only from the strategy's perspective. No shadow position, fill, P&L, rejection, drawdown, or state may alter signal generation or primary order management.

The twin exposes no broker object, webhook, connector, MCP control, external submission method, or activation handle. Every twin summary contains `execution_authorized: false`.

## 6. Bar sequencing and causality

For each chart bar at index `N`, runtime already has the underlying standard `real` bar and the transformed strategy/chart bar.

When RT01 is enabled:

1. Runtime provides the standard real bar to `MirroredEmulator` for bar `N`.
2. `MirroredEmulator.process_bar(primary_fill_bar, N)` first verifies that the paired real bar has the same timestamp/bar identity expected for `N`.
3. The shadow emulator processes the real bar using the existing emulator's normal pending-order/intrabar semantics.
4. The primary emulator processes the primary fill bar exactly as it did before RT01.
5. The strategy evaluates **once**, against the same HA chart/state it used before RT01.
6. Strategy order mutations are mirrored to both emulators for future processing.

No future standard bar may be visible to the shadow before the primary reaches the same bar index. A timestamp mismatch or absent real bar marks the twin `DEGRADED`/`INVALID` for that bar and suppresses shadow mutation; the primary continues normally.

## 7. Mirrored order contract

Every mutating emulator API used by ICARUS must be explicitly forwarded rather than relying on generic reflection. Initial required contract:

- `entry()`
- `exit()`
- `close()`
- `cancel()`

If current code uses additional mutating methods, implementation must inventory and add them before enabling RT01. A contract test fails if `Emulator` acquires a new mutator that `MirroredEmulator` does not classify.

Each call creates an immutable intent record containing at least:

- `intent_seq`;
- bar index and timestamp;
- method/kind;
- entry/exit id;
- direction/side;
- quantity;
- primary arguments exactly as received;
- primary position before intent;
- shadow position before intent;
- whether the intent was applied, ignored, or structurally impossible in shadow;
- `execution_authorized: false`.

### 7.1 Market entries

The same entry id, direction, and quantity are submitted to both emulators. Under existing emulator semantics they fill on their respective next-bar opens: the primary at its configured fill representation and the shadow at the real-bar open.

No synthetic-to-real price substitution is made manually; the real emulator determines its own fill from the real bar.

### 7.2 Limit entries

The exact absolute limit level generated by the strategy is mirrored. If that level never trades on the real bar, the shadow order does not fill. That disagreement is evidence, not an error.

### 7.3 Relative profit/loss exits

`profit=` and `loss=` tick-distance orders are forwarded unchanged. The shadow emulator therefore resolves those distances from its own real entry fill, which preserves the strategy's intended tick geometry while using the actual shadow basis.

### 7.4 Absolute stop/limit exits

Absolute `stop=` and `limit=` values are forwarded unchanged. They are **not shifted** merely because the real entry differs from the HA entry. This is intentionally conservative: if an absolute level derived by the strategy is not viable against the real-price path, the twin must expose that fact rather than silently improving the order.

### 7.5 Dynamic replacements, partial exits, cancels, reversals

Re-issued exit ids, partial quantities, cancellation, close, opposite-direction reversal, and pyramiding are mirrored in original call order. The existing emulator remains the sole semantics implementation.

If the primary manages a position that the shadow never filled, the corresponding shadow mutation is recorded as unmatched/no-position and must not manufacture a position merely to preserve apparent parity.

## 8. Pairing and evidence identity

Pairing is based on the mirrored intent sequence, not fuzzy timestamps or P&L similarity.

Required identity fields:

- asset;
- run/epoch id;
- `intent_seq`;
- primary order id;
- entry sequence;
- exit id/sequence where applicable;
- bar index/timestamp.

Partial exits remain separate fill/trade pieces internally, but reporting also aggregates them into an **entry episode** so a multi-leg primary position can be compared with its real-price shadow counterpart as one economic trade.

An episode can end as:

- `PAIRED_CLOSED`;
- `PRIMARY_ONLY_FILL`;
- `SHADOW_ONLY_FILL` (possible for resting levels/path ordering);
- `OPEN_BOTH`;
- `OPEN_PRIMARY_ONLY`;
- `OPEN_SHADOW_ONLY`;
- `UNMATCHABLE` with an explicit reason.

No missing counterpart is silently dropped from denominators.

## 9. Warm-up versus live boundary

RT01 runs through warm-up so the owner can compare the existing HA warm-up replay with a same-decision real-price counterfactual over the exact same historical bar set.

Evidence is partitioned by the canonical `live_from_ts` boundary:

- `warmup_reference` / `warmup_real_shadow`;
- `live_reference` / `live_real_shadow`.

The current HA warm-up value remains clearly labelled as reference/artifact when its primary fill basis is synthetic. The real-price twin produces a separate number and never overwrites the existing tile.

State is deterministic from replay. RT01 must not create a second accumulating lifetime P&L that double-counts on process restart. The current run can be reconstructed from the same bar cache and strategy stream; durable evidence snapshots, if persisted, are keyed by run/config/input digest and are immutable/read-only.

## 10. Required metrics

### 10.1 Fill and timing

- mirrored signal/intents count;
- primary entry fills;
- shadow entry fills;
- **entry fill parity** = shadow entry fills / primary entry fills;
- entry price delta in points, ticks, and dollars;
- exit price delta where pairable;
- entry/exit bar delta;
- primary-only and shadow-only fills.

### 10.2 Outcome quality

At entry-episode level:

- primary win rate;
- real-price shadow win rate;
- winner/winner, loser/loser, winner/loser, loser/winner matrix;
- **outcome agreement rate** = same P&L sign / pairable closed episodes;
- **primary-win preservation** = real-shadow winners / pairable primary winners;
- average and median real-shadow P&L;
- profit factor and expectancy for the shadow lane;
- shadow MAE/MFE from real bars;
- maximum shadow equity drawdown.

Break-even episodes are reported separately rather than coerced to win/loss.

### 10.3 Economic realization

Report both:

- `net_realization_ratio = shadow_net / primary_net` when the denominator is numerically meaningful;
- `paired_profit_capture = sum(shadow P&L for pairable primary winners) / sum(primary P&L for those winners)`.

Also report absolute dollar difference. Ratios are `null` with a reason when the denominator is zero/near-zero or sign interpretation would be misleading.

Never convert fill parity into signal accuracy; they are different metrics.

### 10.4 Per-asset attribution

All core metrics are available portfolio-wide and per asset. Event-day/CPI/FOMC attribution is deliberately deferred unless existing causal event labels can be consumed without expanding RT01 into a new research trial.

## 11. Runtime state/API contract

When enabled, each asset state gains a read-only `real_price_shadow` object with a versioned schema, for example:

```json
{
  "schema": "icarus.real_price_shadow/1",
  "enabled": true,
  "status": "READY",
  "execution_authorized": false,
  "fill_basis": "STANDARD_REAL_BAR_EMULATOR",
  "signal_basis": "PRIMARY_ICARUS_ORDER_INTENTS",
  "primary_fill_basis": "chart",
  "warmup": {"...": "metrics"},
  "live": {"...": "metrics"},
  "open_episodes": [],
  "recent_pairs": []
}
```

Portfolio state aggregates the same metrics without changing existing `net`, `live_profit`, `open_profit`, `equity`, or position fields.

Feature configuration must be explicit and behavior-neutral when absent. Proposed runtime/CLI switch: `--shadow-real-fills`; internal config name `shadow_real_fills: bool = False`.

Turning it off restores exact current behavior and resource use.

## 12. Dashboard contract

A narrow read-only functional panel may be added **only after coordination confirms the current UI file split**. The backend feature does not depend on that panel.

Suggested labels:

- `HA reference` — current primary result, with `synthetic fill` badge when applicable;
- `Real-price shadow` — second-emulator result;
- `Outcome agreement`;
- `Primary-win preservation`;
- `P&L realization`;
- `Entry fill parity`;
- `Shadow max DD`;
- paired/unpaired trade counts.

The UI must never label shadow evidence `live`, `broker-filled`, `verified alpha`, or `execution-authorized`. Tooltip text should explicitly state that it is a same-decision real-bar emulator comparison.

No animation, aesthetic system, layout redesign, or broad dashboard refactor is part of RT01.

## 13. Failure behavior

RT01 is fail-isolated.

Twin failures must not pause, flatten, alter, or reject primary ICARUS activity. Instead:

- missing paired real bar -> twin status `DEGRADED`, intent/fill suppressed for that bar;
- timestamp/order violation -> twin status `INVALID`, explicit reason;
- numerical/non-finite value -> reject the affected twin event;
- matcher ambiguity -> keep both records and mark `UNMATCHABLE`;
- exception in twin code -> log error, disable twin for that asset/run, preserve primary operation.

No exception path may fall back to synthetic bars while still claiming `REAL_BAR` evidence.

## 14. Persistence and reproducibility

The source of truth for twin state is deterministic replay of:

1. the primary configuration digest;
2. the exact historical/live raw bar sequence already accepted by the canonical runtime;
3. the mirrored order-intent sequence.

If compact evidence snapshots are persisted, use a versioned immutable run digest containing asset, configuration, bar-range fingerprint, strategy build, and twin schema. Persistence must not contain licensed raw vendor rows beyond existing repository rules.

The implementation must expose enough provenance to reproduce a reported metric from the same input bars.

## 15. Testing strategy

Implementation follows TDD. Required tests include:

### 15.1 Behavior-neutral primary tests

- run an identical deterministic fixture with RT01 off and on;
- assert identical primary decisions, pending orders, fills, closed trades, final strategy state, P&L, and decision/parity digests;
- assert twin code has no import or handle capable of broker submission.

### 15.2 Mirroring unit tests

- market entry: primary HA open differs from real open; same intent, different fills;
- limit entry: primary fills while real shadow never trades the level;
- relative TP/SL resolves from each emulator's own entry basis;
- absolute stop/limit stays at the exact strategy level;
- partial TP followed by stop;
- dynamic exit replacement;
- cancel before fill;
- reversal;
- pyramiding cap;
- primary position exists while shadow position does not;
- shadow position exists while primary does not.

### 15.3 Path-order tests

- real bar touches stop and target in the same bar: existing conservative emulator ordering is preserved;
- gap-through stop/limit uses existing emulator semantics;
- different HA and real intrabar paths produce evidence disagreement without changing primary state.

### 15.4 Causality/integrity tests

- appending future real bars cannot alter prior twin evidence;
- real-bar timestamp must match current chart bar;
- missing standard bar never falls back to HA;
- no bar at `N+1` is available while processing `N`.

### 15.5 Metrics tests

- exact denominator accounting for unmatched trades;
- outcome matrix totals reconcile;
- break-even handling;
- realization ratio null rules;
- max drawdown from shadow equity sequence;
- warm-up/live partition at exact boundary;
- per-asset totals sum to portfolio totals.

### 15.6 Determinism/restart tests

- replaying the same fixture twice yields byte-equivalent normalized evidence;
- restart/re-warm does not double-count historical P&L;
- config/bar fingerprint change creates a different evidence identity.

## 16. Implementation path and file boundaries

Planned product paths after written-spec review and implementation planning:

- **Create:** `icarus_engine/shadow_twin.py`
- **Create:** `tests_engine/test_shadow_twin.py`
- **Modify narrowly:** `icarus_engine/runtime.py` to construct the facade, provide the paired real bar, and expose read-only state
- **Potential modify after file-split confirmation:** `icarus_engine/cli.py` for `--shadow-real-fills`
- **Potential modify after UI split confirmation:** `icarus_engine/dashboard.html` for a read-only comparison panel
- **Potential modify only if needed for state delivery:** `icarus_engine/server.py`

Do not modify:

- `cl_lab/**`, `tests_cl/**`, or CL artifacts;
- Claude P1 forward-rule shadow trader;
- bridge broker/executor behavior;
- activation/approval policy;
- scheduler/automation cadences;
- strategy scoring/entry logic;
- existing HA configuration or preset values;
- broad UI animation/aesthetic files.

## 17. Rollout

1. Land backend twin and tests behind default-off flag.
2. Run deterministic primary-neutrality regression suite.
3. Run existing engine tests and focused emulator/futures/recovery tests.
4. Replay a small known HA fixture and manually inspect paired evidence.
5. Replay the owner's normal warm-up dataset with the current HA configuration and generate side-by-side metrics.
6. Only after evidence is coherent, enable the twin in the owner's launch configuration.
7. Add the read-only dashboard panel after coordination confirms the narrow UI integration hook.

At no stage does RT01 turn on live execution.

## 18. Interpretation contract

The output must support three separate statements and never collapse them:

1. **Signal/reference performance:** what the existing HA-primary run reports.
2. **Real-price shadow performance:** what the same ICARUS order-intent stream produces on standard real bars under emulator assumptions.
3. **Broker realization:** what an actual paper/live broker fills, measured separately by bridge/reality-gap evidence when available.

A strong real-price shadow result would materially increase confidence that the HA engine is identifying genuine tradable moves, but it still does not by itself prove future profitability or broker-level realization.
