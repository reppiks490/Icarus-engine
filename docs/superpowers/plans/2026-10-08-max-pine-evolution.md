# MAX Pine Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a causally correct, instrument-aware Pine v6 MAX strategy beside the frozen Legacy baseline, with ICARUS-informed but strictly validated research transfer, comparison telemetry, and no functional dependency on the ICARUS runtime.

**Architecture:** The implementation is deliberately additive. The exact user Pine source is frozen as an immutable Legacy artifact, while `pine/max_pine_evolution.pine` becomes the standalone TradingView deliverable with `Legacy`, `MAX`, and `Compare` modes. Python under `research/max_pine/` is a research/reference harness only: it reproduces MAX formulas, tests causality, evaluates Legacy-vs-MAX outcomes, and distills ICARUS/Databento findings into versioned evidence receipts; nothing in `icarus/`, `icarus_engine/`, workflows, execution, or production decision paths imports it.

**Tech Stack:** Pine Script v6; Python 3.11+ standard library; pytest >= 8; existing ICARUS research artifacts as read-only evidence inputs.

**Spec:** `docs/superpowers/specs/2026-10-08-max-pine-evolution-design.md`

## Global Constraints

- Existing `pine/icarus_engine.pine`, `icarus/`, `icarus_engine/`, execution workflows, provider collectors, and ICARUS production behavior are read-only for this build.
- Legacy source must be byte-for-byte frozen from the user's canonical Dropbox `Pasted document.txt` before MAX edits begin.
- Pine fills and realized outcomes use standard tradeable OHLC; transformed candles may be feature inputs only when explicitly selected.
- Swing origin time and knowledge time are separate; only knowledge-time state may influence decisions.
- Long and short scoring use separate state and thresholds.
- No Pine value is labeled true MBO/order flow unless the Pine runtime genuinely supplies it; OHLCV-derived flow is always marked proxy.
- Synthetic-only, rejected, artifact, or failed-null ICARUS results are forbidden from promotion into MAX defaults.
- Any ICARUS-derived coefficient requires a versioned evidence receipt with status `EXPERIMENTAL`, `REJECTED`, `SHADOW`, or `PROMOTED`.
- First implementation does not include direct Databento access from Pine, self-modifying Pine, production trading authorization, or cloud model inference.
- Pine compile success in TradingView is a release gate; repository tests cannot substitute for TradingView's compiler.

## Review Focus

1. **Non-standard chart input:** on Heikin-Ashi or another transformed chart, MAX execution geometry must still use standard OHLC and must not silently revert to chart prices.
2. **Unknown instrument root:** `Auto` must fall back to `Generic futures`, report the fallback, and never inherit NQ-only point assumptions.
3. **Pivot confirmation edge:** a pivot may be drawn at its origin for diagnostics, but a decision before `level_known_bar` must remain impossible.
4. **Intrabar ambiguity:** when stop and target are both touched and lower-timeframe order cannot resolve sequence, the outcome must be conservative/worst-case.
5. **Missing or unusable volume:** flow-proxy components must degrade to neutral/unavailable without NaN poisoning or creating a directional vote.

---

## File Structure

### Pine deliverables

- `pine/max/legacy_baseline.pine` — exact frozen copy of the user's canonical Pine source; never edited after Task 1.
- `pine/max/max_pine_evolution.pine` — standalone Pine v6 deliverable implementing `Legacy | MAX | Compare`.
- `pine/max/README.md` — install/compile instructions, mode semantics, proxy disclosures, release checksum/version.
- `pine/max/evidence_manifest.json` — machine-readable list of research coefficients/rules admitted into the current MAX build.

### Research/reference harness

- `research/max_pine/__init__.py` — package marker only.
- `research/max_pine/types.py` — immutable bar/profile/event/result dataclasses and enums shared by the reference modules.
- `research/max_pine/profiles.py` — instrument-profile resolution and normalization constants.
- `research/max_pine/causal_kernel.py` — session handling, standard-price semantics, pivot origin/knowledge timing.
- `research/max_pine/structure.py` — BOS/CHoCH/protected-level/objective reference state machine.
- `research/max_pine/liquidity.py` — pool map, equal-level clustering, penetration/reclaim lifecycle, sweep quality, target room.
- `research/max_pine/microstructure_proxy.py` — OHLCV-only CVD/delta/absorption/divergence and LTF summary reference formulas.
- `research/max_pine/volatility.py` — percentile/expansion/compression/shock state and fitness.
- `research/max_pine/scoring.py` — independent long/short evidence, vetoes, conviction grades.
- `research/max_pine/execution.py` — fast/endurance envelopes and conservative path resolution.
- `research/max_pine/compare.py` — Legacy/MAX disagreement and forward-outcome evaluation.
- `research/max_pine/distill.py` — read-only teacher experiment runner for Databento/ICARUS derived context.
- `research/max_pine/evidence.py` — receipt schema validation and promotion eligibility.

### Tests

- `tests/test_max_pine_source_contract.py`
- `tests/test_max_pine_profiles.py`
- `tests/test_max_pine_causality.py`
- `tests/test_max_pine_structure.py`
- `tests/test_max_pine_liquidity.py`
- `tests/test_max_pine_proxy.py`
- `tests/test_max_pine_scoring.py`
- `tests/test_max_pine_execution.py`
- `tests/test_max_pine_compare.py`
- `tests/test_max_pine_distillation.py`
- `tests/fixtures/max_pine/` — deterministic NQ/MNQ, SI, transformed-chart, and ambiguous-intrabar fixture data.

No existing ICARUS runtime file is modified by this plan.

---

### Task 1: Freeze the Canonical Legacy Baseline and Build Guardrails

**Files:**
- Create: `pine/max/legacy_baseline.pine`
- Create: `pine/max/README.md`
- Create: `tests/test_max_pine_source_contract.py`
- Create: `tests/fixtures/max_pine/legacy_source.sha256`

**Interfaces:**
- Consumes: user's canonical Dropbox `Pasted document.txt`.
- Produces: immutable Legacy source plus `LEGACY_SHA256` read by later source-contract tests.

- [ ] **Step 1: Materialize and checksum the canonical Dropbox file**

Compute SHA-256 and line count from the exact current file; copy bytes unchanged to `pine/max/legacy_baseline.pine` and write only the digest string to `tests/fixtures/max_pine/legacy_source.sha256`.

- [ ] **Step 2: Write the failing immutable-source test**

`tests/test_max_pine_source_contract.py::test_legacy_baseline_matches_frozen_sha256` must hash `pine/max/legacy_baseline.pine` and assert equality with the fixture digest. Add `test_existing_icarus_pine_is_not_a_max_dependency` asserting `pine/max/` contains no import/include path to `pine/icarus_engine.pine`.

- [ ] **Step 3: Run the source-contract test and verify it fails before the files exist**

Run: `python -m pytest tests/test_max_pine_source_contract.py -v`

Expected: FAIL because the baseline/checksum artifacts are absent.

- [ ] **Step 4: Add the exact baseline and README contract**

`pine/max/README.md` must state that `legacy_baseline.pine` is immutable, `max_pine_evolution.pine` is the evolved deliverable, ICARUS runtime is not modified, and real TradingView compile validation is required before release.

- [ ] **Step 5: Re-run the test**

Run: `python -m pytest tests/test_max_pine_source_contract.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pine/max tests/test_max_pine_source_contract.py tests/fixtures/max_pine/legacy_source.sha256
git commit -m "test: freeze MAX Pine legacy baseline"
```

---

### Task 2: Establish Shared Types and Instrument Profiles

**Files:**
- Create: `research/max_pine/__init__.py`
- Create: `research/max_pine/types.py`
- Create: `research/max_pine/profiles.py`
- Create: `tests/test_max_pine_profiles.py`
- Create: `tests/fixtures/max_pine/instruments.json`

**Interfaces:**
- Consumes: ticker root, exchange, minimum tick, point value, chart timeframe.
- Produces: `InstrumentProfile`, `ProfileName`, and `resolve_profile(symbol: str, exchange: str, mintick: float) -> InstrumentProfile`.

- [ ] **Step 1: Write profile-resolution tests**

Tests must pin these cases: `NQ1!/MNQ1! -> NQ_MNQ`, `ES1!/MES1! -> ES_MES`, `SI1! -> SILVER`, `GC1!/MGC1! -> GOLD`, common crypto symbols -> `CRYPTO`, and unknown futures -> `GENERIC_FUTURES`. Assert Silver's price-bin floor is tick-aware and strictly below `1.0` price unit when `mintick < 1.0`.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_profiles.py -v`

Expected: FAIL because `research.max_pine.profiles` does not exist.

- [ ] **Step 3: Implement profile types**

Create `ProfileName` enum and frozen `InstrumentProfile` dataclass in `types.py`; implement `resolve_profile(...)` in `profiles.py`. Profile fields must include `name`, `session_tz`, `session_template`, `mintick`, `point_value`, `market_profile_min_ticks`, and `supports_volume_proxy`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_max_pine_profiles.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research/max_pine tests/test_max_pine_profiles.py tests/fixtures/max_pine/instruments.json
git commit -m "feat: add MAX Pine instrument profiles"
```

---

### Task 3: Build the Causal Price/Session/Pivot Kernel

**Files:**
- Create: `research/max_pine/causal_kernel.py`
- Create: `tests/test_max_pine_causality.py`
- Create: `tests/fixtures/max_pine/causal_bars.json`

**Interfaces:**
- Consumes: `Bar`, `InstrumentProfile`, pivot strength, standard-price series, optional transformed feature series.
- Produces: `ConfirmedPivot(origin_index: int, known_index: int, price: float, side: int)`, session identity, and prefix-stable causal state.

- [ ] **Step 1: Write causality tests**

Add tests for delayed pivot confirmation, prefix invariance, future-garbage invariance, session roll, transformed-feature/standard-fill separation, and an intentionally leaky positive-control helper that the harness must flag as non-prefix-stable.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_causality.py -v`

Expected: FAIL because causal kernel interfaces do not exist.

- [ ] **Step 3: Implement `confirm_pivots(...)` and session helpers**

Exact signatures:

```python
def confirm_pivots(bars: list[Bar], strength: int) -> list[ConfirmedPivot]: ...
def session_key(ts: datetime, profile: InstrumentProfile) -> str: ...
def assert_prefix_stable(run_fn, bars: list[Bar], cut: int) -> bool: ...
```

`known_index` must equal the confirmation bar, never the origin bar.

- [ ] **Step 4: Run causality tests**

Run: `python -m pytest tests/test_max_pine_causality.py -v`

Expected: PASS, including the leaky positive control being detected.

- [ ] **Step 5: Commit**

```bash
git add research/max_pine/causal_kernel.py tests/test_max_pine_causality.py tests/fixtures/max_pine/causal_bars.json
git commit -m "feat: add causal MAX Pine kernel"
```

---

### Task 4: Implement Structure State and Knowledge-Time BOS/CHoCH

**Files:**
- Create: `research/max_pine/structure.py`
- Create: `tests/test_max_pine_structure.py`

**Interfaces:**
- Consumes: `Bar`, confirmed pivots from Task 3.
- Produces: `StructureState.update(bar: Bar, pivots: Sequence[ConfirmedPivot]) -> StructureEvent`, `alignment(direction: int) -> float`, `protective_level(direction: int, price: float) -> float | None`, and `objective_level(...)`.

- [ ] **Step 1: Write failing structure tests**

Pin BOS up/down, CHoCH up/down, event freshness decay, protected swing, objective swing, and the invariant that a structure event cannot reference a pivot before its `known_index`.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_structure.py -v`

Expected: FAIL because `StructureState` is absent.

- [ ] **Step 3: Implement the state machine**

Use close-through confirmation for BOS/CHoCH; wick-only breaches remain liquidity-layer events. Fresh same-direction CHoCH must score above fresh same-direction BOS; stale events decay toward neutral.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_max_pine_structure.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research/max_pine/structure.py tests/test_max_pine_structure.py
git commit -m "feat: add causal structure state for MAX Pine"
```

---

### Task 5: Implement the Multi-Pool Liquidity and Sweep State Machine

**Files:**
- Create: `research/max_pine/liquidity.py`
- Create: `tests/test_max_pine_liquidity.py`
- Create: `tests/fixtures/max_pine/liquidity_sequences.json`

**Interfaces:**
- Consumes: `Bar`, ATR, confirmed structure pivots, session extremes/open.
- Produces: `LiquidityMap.update(...) -> SweepEvent | None`, `nearest_pool(price: float, side: int) -> LiquidityPool | None`, and target-room metrics.

- [ ] **Step 1: Write failing pool/sweep tests**

Cover prior-session high/low, session high/low, confirmed swing high/low, equal-high/low clustering, session open, repeated touches, same-bar reclaim, multi-bar reclaim, excessive-penetration breakout, reclaim timeout, and nearest opposing target room.

- [ ] **Step 2: Add sweep-quality assertions**

Tests must expose the four component scores separately: penetration quality, reclaim speed, rejection quality, pool importance. Assert the composite is bounded `[0,1]` but do not assert it is a probability.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_liquidity.py -v`

Expected: FAIL because `LiquidityMap` is absent.

- [ ] **Step 4: Implement liquidity lifecycle**

Pool state enum: `LIVE`, `PENDING`, `RAID_CONFIRMED`, `ACCEPTED`, `RETIRED`. Pool age begins at `known_index`, not pivot origin.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_max_pine_liquidity.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add research/max_pine/liquidity.py tests/test_max_pine_liquidity.py tests/fixtures/max_pine/liquidity_sequences.json
git commit -m "feat: add MAX Pine liquidity state machine"
```

---

### Task 6: Implement Volatility Permission and OHLCV Microstructure Proxies

**Files:**
- Create: `research/max_pine/volatility.py`
- Create: `research/max_pine/microstructure_proxy.py`
- Create: `tests/test_max_pine_proxy.py`
- Create: `tests/fixtures/max_pine/proxy_sequences.json`

**Interfaces:**
- Consumes: standard `Bar` stream and optional lower-timeframe completed intrabars.
- Produces: `VolatilityState`, `FlowProxyState`, `summarize_intrabar_path(...)`.

- [ ] **Step 1: Write volatility tests**

Assert dead-vol veto, shock-vol veto, mid-band fitness preference, compression-to-expansion reward, and no monotonic assumption that higher ATR is always better.

- [ ] **Step 2: Write flow-proxy tests**

Assert session-anchored CVD, normalized CVD slope, delta z-score, relative-volume z-score, effort/result absorption, price/CVD divergence, and `is_proxy=True`.

- [ ] **Step 3: Add missing-volume and LTF-path tests**

Missing/zero volume must yield neutral/unavailable flow without NaN poisoning. Intrabar summary must use all completed provided intrabars and expose excursion order when resolvable.

- [ ] **Step 4: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_proxy.py -v`

Expected: FAIL because proxy modules do not exist.

- [ ] **Step 5: Implement the reference formulas**

Keep outputs bounded and explicitly tagged `proxy=True`; no field name may imply live depth or aggressor truth.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_max_pine_proxy.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add research/max_pine/volatility.py research/max_pine/microstructure_proxy.py tests/test_max_pine_proxy.py tests/fixtures/max_pine/proxy_sequences.json
git commit -m "feat: add MAX Pine volatility and flow proxies"
```

---

### Task 7: Implement Independent Directional Scoring, Vetoes, and Grades

**Files:**
- Create: `research/max_pine/scoring.py`
- Create: `tests/test_max_pine_scoring.py`

**Interfaces:**
- Consumes: sweep event, structure alignment, volatility fitness, flow proxy, VWAP/location score, momentum/exhaustion score, target room, session state.
- Produces: `ScoreResult(long_score: float, short_score: float, long_veto: str, short_veto: str, grade: str, actionable_direction: int)`.

- [ ] **Step 1: Write score-isolation tests**

Mutating bullish evidence must not change the short threshold/state; mutating bearish evidence must not change the long threshold/state. Add a regression test for the current shared-threshold defect identified in Legacy.

- [ ] **Step 2: Write hard-gate tests**

No valid session, no sweep trigger, volatility veto, insufficient target room in `Strict` mode, or invalid causal state must block action regardless of soft score.

- [ ] **Step 3: Write grade tests**

Grades `S/A/B/C` map from configurable conviction bands but the numeric score is named `conviction`, never `probability`. The test must reject source text that presents score values with `%` probability semantics.

- [ ] **Step 4: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_scoring.py -v`

Expected: FAIL because scoring interfaces are absent.

- [ ] **Step 5: Implement scoring**

Default trigger architecture: a confirmed liquidity raid/reclaim originates the opportunity; other evidence confirms, weakens, or vetoes it.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_max_pine_scoring.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add research/max_pine/scoring.py tests/test_max_pine_scoring.py
git commit -m "feat: add independent MAX Pine evidence scoring"
```

---

### Task 8: Implement Conservative Execution and Fast/Endurance Lifecycles

**Files:**
- Create: `research/max_pine/execution.py`
- Create: `tests/test_max_pine_execution.py`
- Create: `tests/fixtures/max_pine/execution_paths.json`

**Interfaces:**
- Consumes: standard OHLC, optional resolved LTF path, score result, sweep extreme, ATR, structure objective/protective level.
- Produces: `ExecutionEnvelope`, `resolve_bar_outcome(...)`, fast/endurance lifecycle actions.

- [ ] **Step 1: Write failing execution tests**

Cover standard-price entry/fill, transformed-chart feature separation, gap-through stop, both-stop-and-target-touch worst case, LTF-resolved target-first/stop-first sequence, structural stop floor, ATR noise floor, time stop, filtered trail, and HTF endurance objective.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_execution.py -v`

Expected: FAIL because execution module is absent.

- [ ] **Step 3: Implement execution reference logic**

Exact public interfaces:

```python
def build_envelope(ctx: ExecutionContext, horizon: str) -> ExecutionEnvelope: ...
def resolve_bar_outcome(bar: Bar, envelope: ExecutionEnvelope, ltf_path: list[Bar] | None) -> FillOutcome: ...
```

When both stop and target touch and `ltf_path` cannot prove order, stop wins.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_max_pine_execution.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research/max_pine/execution.py tests/test_max_pine_execution.py tests/fixtures/max_pine/execution_paths.json
git commit -m "feat: add MAX Pine execution reference model"
```

---

### Task 9: Build the Pine v6 MAX Script from the Frozen Baseline

**Files:**
- Create: `pine/max/max_pine_evolution.pine`
- Modify: `tests/test_max_pine_source_contract.py`
- Create: `tests/fixtures/max_pine/pine_contract.json`

**Interfaces:**
- Consumes: frozen Legacy baseline plus Task 2-8 reference formulas/contracts.
- Produces: standalone Pine v6 script with `Engine Mode = Legacy | MAX | Compare` and MAX build/version constants.

- [ ] **Step 1: Extend static source-contract tests**

Assert the MAX source contains: Pine v6 declaration; engine-mode input with exactly `Legacy`, `MAX`, `Compare`; explicit standard-ticker OHLC path; explicit `request.security_lower_tf` LTF path; separate long/short thresholds; proxy disclosure; MAX version/schema constants; no universal `max(1.0, ...)` Market Profile floor in MAX logic; and no import/runtime call into Python ICARUS.

- [ ] **Step 2: Run the source-contract test and verify failure**

Run: `python -m pytest tests/test_max_pine_source_contract.py -v`

Expected: FAIL because `max_pine_evolution.pine` does not exist.

- [ ] **Step 3: Copy Legacy into the new deliverable without editing the frozen file**

Use `legacy_baseline.pine` as the source ancestor. `Legacy` mode must preserve its original decision logic; correctness fixes that change behavior belong only in `MAX` unless explicitly documented as display-only diagnostics.

- [ ] **Step 4: Port Tasks 2-8 into MAX Pine functions/state**

Pine functions and state names must follow the reference interfaces closely enough that deterministic fixtures can map component-by-component. Use tick/ATR normalization and instrument profiles, causal structure/liquidity state, volatility permission, OHLCV flow proxies, independent directional scores, and fast/endurance execution.

- [ ] **Step 5: Implement Compare mode shadow accounting**

Only one selected engine may place strategy orders; the shadow engine records signals, direction, timing, scores, vetoes, and outcome fields without duplicate execution.

- [ ] **Step 6: Run source-contract tests**

Run: `python -m pytest tests/test_max_pine_source_contract.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pine/max/max_pine_evolution.pine tests/test_max_pine_source_contract.py tests/fixtures/max_pine/pine_contract.json
git commit -m "feat: build MAX Pine v6 strategy"
```

---

### Task 10: Add Visualization Hierarchy and JSON Telemetry

**Files:**
- Modify: `pine/max/max_pine_evolution.pine`
- Create: `tests/test_max_pine_compare.py`
- Create: `tests/fixtures/max_pine/telemetry_schema.json`

**Interfaces:**
- Consumes: MAX/Legacy score and event state.
- Produces: low-clutter S/A/B/C visuals and versioned JSON alert payloads.

- [ ] **Step 1: Write telemetry/source tests**

Assert required fields: schema version, build hash/version, ticker, exchange, profile, timeframe, event time, mode, direction, pool class/level, penetration, reclaim age, sweep components, long/short scores, component scores, volatility state, flow-proxy metadata, target room, stop/targets, grade, veto, proxy flags, causality/debug flags.

- [ ] **Step 2: Write visualization hierarchy tests**

Static contract must expose a minimum-grade display input, default suppression of lower-grade event labels, and a debug mode that can reveal reconstructed origin markers without feeding decisions.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_compare.py -v`

Expected: FAIL until telemetry/visualization contracts are present.

- [ ] **Step 4: Implement Pine JSON alert construction and chart hierarchy**

Alerts contain research state only, no secrets or production-authorization claim. Labels must distinguish proxy state and reconstructed diagnostics.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_max_pine_compare.py tests/test_max_pine_source_contract.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pine/max/max_pine_evolution.pine tests/test_max_pine_compare.py tests/fixtures/max_pine/telemetry_schema.json
git commit -m "feat: add MAX Pine grading and telemetry"
```

---

### Task 11: Build the ICARUS/Databento Teacher and Evidence-Receipt Pipeline

**Files:**
- Create: `research/max_pine/evidence.py`
- Create: `research/max_pine/distill.py`
- Create: `pine/max/evidence_manifest.json`
- Create: `tests/test_max_pine_distillation.py`
- Create: `tests/fixtures/max_pine/evidence_receipts/`

**Interfaces:**
- Consumes: read-only ICARUS research artifacts and derived Databento depth context already present/available to research jobs.
- Produces: `EvidenceReceipt`, teacher evaluation tables, and a manifest of only eligible Pine-visible coefficients/rules.

- [ ] **Step 1: Write receipt-schema tests**

`EvidenceReceipt` must require `id`, `version`, `source_dataset`, `period`, `sample_count`, `cost_model`, `test_family`, `tune_result`, `hold_result`, `forward_result`, `multiple_testing_method`, `status`, `pine_features`, and `notes`.

- [ ] **Step 2: Write promotion-rejection tests**

Explicit fixtures must reject: synthetic-only optimizer winner, real-data rule with failed null/permutation test, CL-lab rejected candidate, failed ML candidate, HA-fill artifact, and depth feature with no held-out incremental Pine-proxy value.

- [ ] **Step 3: Write eligible-shadow test**

A causal, held-out-positive, stress-cost-surviving teacher relationship that has not yet met forward threshold may be `SHADOW` but not `PROMOTED`.

- [ ] **Step 4: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_distillation.py -v`

Expected: FAIL because evidence pipeline does not exist.

- [ ] **Step 5: Implement receipt validation and read-only teacher evaluation**

`distill.py` may read existing derived depth/research context but must not fetch paid data, mutate ICARUS research registries, alter champions, or authorize execution.

- [ ] **Step 6: Generate initial evidence manifest**

The first manifest may legitimately contain zero `PROMOTED` coefficients. Existing validated mechanical/parity defaults are marked separately from alpha claims.

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_max_pine_distillation.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add research/max_pine/evidence.py research/max_pine/distill.py pine/max/evidence_manifest.json tests/test_max_pine_distillation.py tests/fixtures/max_pine/evidence_receipts
git commit -m "feat: add MAX Pine evidence promotion pipeline"
```

---

### Task 12: Run Legacy-vs-MAX Evaluation on SI and NQ/MNQ

**Files:**
- Create: `research/max_pine/compare.py`
- Create: `tests/test_max_pine_compare.py` if not already created; otherwise extend it.
- Create: `research/results/max_pine/README.md`
- Create: `research/results/max_pine/latest_summary.json`

**Interfaces:**
- Consumes: causal bar fixtures/available historical research bars, Legacy shadow decisions, MAX decisions.
- Produces: `ComparisonRecord` and aggregate metrics by instrument, timeframe, session, direction, and grade.

- [ ] **Step 1: Write comparison tests**

Pin categories `BOTH_ACCEPT`, `LEGACY_ONLY`, `MAX_ONLY`, `BOTH_REJECT`, `DIRECTION_DISAGREE`; assert timing delta, MFE, MAE, 1/3/6/12/24-bar forward returns, target-first/stop-first outcome, and expectancy fields.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_max_pine_compare.py -v`

Expected: FAIL because comparison engine is incomplete.

- [ ] **Step 3: Implement comparison engine**

Exact interface:

```python
def compare_runs(legacy: Sequence[SignalRecord], max_run: Sequence[SignalRecord], bars: Sequence[Bar]) -> list[ComparisonRecord]: ...
```

No metric may use bars occurring before the signal became knowable.

- [ ] **Step 4: Run deterministic comparison tests**

Run: `python -m pytest tests/test_max_pine_compare.py -v`

Expected: PASS.

- [ ] **Step 5: Run available SI and NQ/MNQ research comparisons**

Use existing lawful/local historical sources already available in the repo/cache. If SI history is unavailable in the current runner, publish that limitation rather than substitute NQ or synthetic data.

- [ ] **Step 6: Write `latest_summary.json`**

Report sample counts and metrics with explicit provenance. Do not call MAX better unless the selected unseen-data metrics actually improve.

- [ ] **Step 7: Commit**

```bash
git add research/max_pine/compare.py research/results/max_pine tests/test_max_pine_compare.py
git commit -m "test: compare MAX Pine against Legacy"
```

---

### Task 13: Full Validation and Release Candidate

**Files:**
- Modify: `pine/max/README.md`
- Modify: `pine/max/max_pine_evolution.pine`
- Create: `docs/MAX_PINE_RELEASE_NOTES.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: release-candidate Pine source plus verification evidence.

- [ ] **Step 1: Run focused MAX test suite**

Run:

```bash
python -m pytest \
  tests/test_max_pine_source_contract.py \
  tests/test_max_pine_profiles.py \
  tests/test_max_pine_causality.py \
  tests/test_max_pine_structure.py \
  tests/test_max_pine_liquidity.py \
  tests/test_max_pine_proxy.py \
  tests/test_max_pine_scoring.py \
  tests/test_max_pine_execution.py \
  tests/test_max_pine_compare.py \
  tests/test_max_pine_distillation.py -v
```

Expected: all PASS.

- [ ] **Step 2: Run repository regression tests**

Run: `python -m pytest`

Expected: existing suite remains green; any unrelated pre-existing failure must be documented separately and must not be hidden by MAX changes.

- [ ] **Step 3: Verify isolation from ICARUS runtime**

Run `git diff --name-only <implementation-base>...HEAD` and assert no file under `icarus/`, `icarus_engine/`, `.github/workflows/`, provider collection paths, or existing `pine/icarus_engine.pine` changed.

- [ ] **Step 4: Verify Legacy checksum again**

Run: `python -m pytest tests/test_max_pine_source_contract.py::test_legacy_baseline_matches_frozen_sha256 -v`

Expected: PASS.

- [ ] **Step 5: Compile in TradingView Pine Editor**

Paste `pine/max/max_pine_evolution.pine` into TradingView Pine Editor using Pine v6. Expected: zero compile errors. Record any compiler diagnostic exactly; fix through a new test/commit rather than ad-hoc edits.

- [ ] **Step 6: Smoke-test chart behavior**

On SI1! 10m and NQ/MNQ 10m, verify `Legacy`, `MAX`, and `Compare` load; standard-price fills are active; MAX instrument profile resolves correctly; debug origin markers do not alter decisions; alerts produce valid JSON.

- [ ] **Step 7: Write release notes**

`docs/MAX_PINE_RELEASE_NOTES.md` must enumerate: Legacy checksum; MAX build/version; behavior changes; evidence-manifest statuses; known limitations; whether SI/NQ comparisons improved, degraded, or remain inconclusive; and explicit statement that MAX does not modify ICARUS runtime.

- [ ] **Step 8: Commit release candidate**

```bash
git add pine/max/README.md pine/max/max_pine_evolution.pine docs/MAX_PINE_RELEASE_NOTES.md
git commit -m "docs: prepare MAX Pine release candidate"
```

- [ ] **Step 9: Request whole-branch review**

Review must specifically check causality, Legacy isolation, instrument normalization, Pine proxy labeling, score-direction isolation, and whether any research claim exceeds its evidence receipt.

---

## Self-Review Results

- **Spec coverage:** All delivery phases 0-7 map to Tasks 1-13. Instrument profiles, causal pivots, structure/liquidity, volatility/proxies, scoring/grading, execution, telemetry, Databento teaching, evidence receipts, comparison, and release gates are represented.
- **No ICARUS runtime mutation:** Plan intentionally creates new files under `pine/max/`, `research/max_pine/`, tests, and docs only. Existing runtime paths are explicit no-touch zones.
- **Type consistency:** Shared `Bar`, `InstrumentProfile`, `ConfirmedPivot`, structure/liquidity events, scoring result, execution envelope, signal/comparison record, and evidence receipt are defined before consumers.
- **Review-focus coverage:** Non-standard charts -> Tasks 3/8/13; unknown instrument -> Task 2; pivot knowledge time -> Tasks 3-5; intrabar ambiguity -> Task 8; missing volume -> Task 6.
- **Promotion discipline:** Synthetic/rejected/artifact findings are explicitly rejected in Task 11 tests; zero promoted alpha in the initial manifest is an acceptable result.
