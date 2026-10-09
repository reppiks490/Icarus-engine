# MAX Pine Evolution — Design Specification

Status: DESIGN / RESEARCH ONLY  
Date: 2026-10-08  
Branch: `max-pine-architecture`  
Production or execution authorization: **false**

## 1. Purpose

MAX is the evolved Pine/TradingView descendant of the user's existing large Pine strategy, informed by the validated mechanics and negative findings inside ICARUS. The objective is not to replace the existing strategy blindly or to port every ICARUS component. The objective is to preserve Legacy behavior as an exact benchmark, add a strictly causal and instrument-aware MAX path beside it, and promote only mechanisms that survive real-data validation.

The intended operating model is:

`ICARUS data/research -> offline validation/distillation -> versioned MAX rules/coefficients -> TradingView Pine -> live/shadow telemetry -> ICARUS evaluation -> future validated MAX revisions`

MAX must never imply that TradingView has access to Databento MBO/MBP-10, true aggressor flow, Python state, or any other data unavailable to the Pine runtime.

## 2. Non-negotiable invariants

1. **Legacy remains reproducible.** The existing strategy remains available as an untouched benchmark. MAX changes must not silently alter Legacy outputs.
2. **Causality over visual attractiveness.** A level/event may have an historical origin bar, but MAX must separately record when that information became knowable. Decisions and score history use knowledge time, never reconstructed origin time.
3. **No lookahead/repaint dependence.** Higher-timeframe data, pivots, lower-timeframe data, and session state must use causal idioms. Any visualization reconstructed backward is explicitly diagnostic and must never feed decisions.
4. **No fake order flow.** Standard TradingView bars provide only OHLCV. Any close-location delta/CVD/absorption calculation is labeled a proxy. True depth/aggressor evidence may train offline calibrations but is not represented as live MBO inside Pine.
5. **Instrument normalization is mandatory.** NQ/MNQ point assumptions must not leak into SI, GC, ES, crypto, or generic futures. Parameters are expressed in ticks, ATR, R, percentages, or an explicit instrument profile.
6. **Hard gates and soft evidence are separate.** A hard failure blocks an opportunity. Soft layers change conviction but cannot manufacture a trigger.
7. **No arbitrary probability labels.** A `92` score is a score unless calibration demonstrates that it can be interpreted probabilistically.
8. **Negative ICARUS results are first-class evidence.** Rejected rules, failed holdouts, failed permutation tests, and failed ML families must not be resurrected merely because in-sample or synthetic numbers look attractive.
9. **Real fills remain real-price fills.** Heikin-Ashi or transformed prices may inform features, but execution/backtest fills must use tradeable standard prices unless a diagnostic artifact mode is explicitly selected and labeled.
10. **Research-only telemetry.** Pine alerts may emit MAX state and feature vectors for offline research. They do not grant ICARUS or MAX production authority.

## 3. Modes

MAX will expose three top-level operating modes:

- `Legacy`: exact current strategy behavior, used as the control.
- `MAX`: evolved causal/instrument-aware engine.
- `Compare`: runs both decision paths side-by-side and records disagreements, timing deltas, and outcomes.

Diagnostic visualization may additionally expose `Origin reconstruction`, but this mode is forbidden from decision logic.

## 4. Canonical price/data kernel

### 4.1 Standard-price source

When the chart is Heikin-Ashi or another transformed chart type, MAX must retrieve standard tradeable OHLC through a standard ticker/security request. Signal features may optionally use transformed data only when explicitly enabled; execution geometry and realized outcome measurement use standard prices.

### 4.2 Timeframe handling

- Main-chart calculations run on completed bars.
- Higher-timeframe context uses confirmed higher-timeframe values only.
- Lower-timeframe context uses intrabar arrays where available rather than a single sampled lower-timeframe value.
- No higher-timeframe or lower-timeframe helper may leak future bars into the current decision.

### 4.3 Session clock

All session calculations must have an explicit timezone and session definition. MAX must distinguish RTH/ETH when relevant and avoid treating a calendar-day reset as equivalent to an exchange-session reset.

## 5. Instrument profile layer

### 5.1 Profiles

Initial profiles:

- `Auto`
- `NQ/MNQ`
- `ES/MES`
- `SI / Silver`
- `GC/MGC / Gold`
- `Metals generic`
- `Crypto`
- `Generic futures`

`Auto` resolves from ticker root/exchange when deterministically recognizable; otherwise it falls back to Generic futures and visibly reports that choice.

### 5.2 What profiles may control

Profiles may set only market-microstructure normalization and safe defaults, including:

- tick size / point value helper metadata;
- default session template;
- ATR lookbacks or percentile windows;
- sane tick/ATR clamps for zones and stops;
- minimum liquidity-level separation;
- visualization precision;
- optional session priors that have explicit provenance.

Profiles must **not** silently inject unvalidated directional alpha.

### 5.3 Removal of NQ leakage

Any existing NQ-specific fixed point target, Initial Balance prior, overnight prior, Market Profile price-bin floor, or hour-breach statistic must either:

1. move behind an NQ-only profile, or
2. be replaced with tick/ATR normalized logic, or
3. be removed from MAX while remaining untouched in Legacy.

The Market Profile bin width in MAX must never use a universal `>= 1.0 price-unit` floor. It must use tick-aware and ATR-aware bounds.

## 6. Causal structure engine

MAX structure state tracks:

- confirmed swing highs/lows;
- `pivot_origin_bar`;
- `level_known_bar`;
- BOS up/down;
- CHoCH up/down;
- current structural trend;
- last structural event and age;
- protected level;
- nearest structural objective.

Swing confirmation lag is preserved. A pivot is never usable before the right-side confirmation bars have closed.

### 6.1 Continuous structure score

Structure is not a single Boolean vote. It is a bounded directional score that considers:

- current trend alignment;
- fresh CHoCH in trade direction;
- fresh BOS in trade direction;
- recent opposing structure break;
- age/decay of the last event.

Fresh CHoCH receives greater incremental weight than continuation BOS. Stale events decay toward neutral.

## 7. Liquidity-map state machine

MAX replaces the one-candle/latest-pivot-only sweep model with a causal state machine.

### 7.1 Pool classes

Initial Pine-visible pool classes:

- prior-session high;
- prior-session low;
- current-session high;
- current-session low;
- confirmed swing high;
- confirmed swing low;
- equal highs;
- equal lows;
- session open.

Each pool stores:

- level;
- class;
- origin bar where applicable;
- known bar;
- touch count;
- state (`live`, `pending penetration`, `confirmed raid`, `accepted/broken`, `retired`);
- last interaction bar.

### 7.2 Equal-level clustering

Nearby confirmed levels are clustered using a tick/ATR-aware tolerance. Repeated defense increases pool significance but is capped so repeated noise does not create unbounded conviction.

### 7.3 Sweep lifecycle

A sweep opportunity has explicit stages:

1. live pool;
2. penetration beyond the pool by at least a minimum normalized amount;
3. pending reclaim window;
4. reclaim/failure of auction;
5. confirmed sweep; or
6. acceptance/breakout when penetration is excessive or reclaim fails.

This supports same-bar and multi-bar raids without retroactive confirmation.

### 7.4 Sweep quality

MAX starts from the ICARUS causal decomposition rather than a binary flag:

- penetration quality;
- reclaim speed;
- rejection/wick quality;
- pool importance / touch history.

The exact production weights are not assumed to be alpha. Initial weights are parity defaults only and remain subject to offline calibration. MAX must expose the component values separately in telemetry.

## 8. Target-room / liquidity-magnet engine

A confirmed sweep is not actionable if there is insufficient clean distance to the nearest relevant opposing liquidity/structure objective.

MAX calculates normalized room in ATR and R terms. This is a hard or semi-hard gate depending on selected research mode:

- `Strict`: insufficient room vetoes the setup.
- `Score`: insufficient room strongly reduces conviction but does not fully veto.

Compare mode records both outcomes for offline evaluation.

## 9. Volatility permission engine

MAX uses volatility as market-state permission rather than a generic momentum vote.

State includes:

- ATR;
- rolling ATR percentile;
- fast/slow ATR expansion ratio;
- realized range vs baseline (`squeeze`/compression state);
- shock range in ATR;
- optional ATR-to-friction proxy when meaningful.

Desired state favors mid-band tradable volatility and compression resolving into expansion. Dead volatility and shock volatility are explicit veto reasons.

The implementation must not assume that higher ATR is monotonically better.

## 10. Pine-visible microstructure proxy engine

### 10.1 Explicit proxy contract

When true bid/ask aggressor volume is unavailable, MAX computes only proxies and labels them as such.

Proxy features:

- close-location signed volume delta;
- session-anchored CVD;
- fast/slow normalized CVD slope;
- delta z-score;
- relative-volume z-score;
- effort-versus-result absorption proxy;
- price/CVD divergence;
- wick/body geometry;
- reclaim speed;
- lower-timeframe intrabar path features where supported.

### 10.2 Databento teacher, not runtime dependency

ICARUS Databento MBO/MBP-10 derived research may be used offline to learn whether Pine-visible features correlate with genuine microstructure states such as:

- touch-clearing aggression;
- multi-level sweeps;
- liquidity withdrawal;
- top-of-book/top-5 refill speed;
- spread normalization;
- post-sweep price response.

A Pine proxy is eligible for promotion only if its relationship to the target state survives held-out/forward validation. Pine never labels the proxy as actual book depth.

## 11. Evidence-family scoring

MAX replaces one shared Boolean vote pile with independent continuous evidence families.

Initial families:

- liquidity/sweep quality;
- structure;
- volatility fitness;
- flow proxy;
- value/location (VWAP premium/discount);
- momentum/exhaustion;
- target room;
- optional session/time context;
- optional ICARUS-distilled proxy coefficients with explicit version/provenance.

### 11.1 Independent long/short scores

Long and short evidence are calculated independently. A shared threshold or shared accumulator must not allow opposite-side evidence to contaminate the other side.

### 11.2 Trigger rule

The default MAX architecture follows ICARUS's cleaner causal premise:

**A liquidity raid/reclaim originates the opportunity. Other families confirm, weaken, or veto it.**

Other families cannot originate a trade in the base MAX mode. Experimental non-sweep triggers require a separately versioned research mode and cannot silently enter MAX default.

## 12. Grading and calibration

User-facing grades may be `S`, `A`, `B`, `C`, plus a numeric conviction score.

The numeric score is initially a bounded **conviction index**, not a claimed probability.

Offline evaluation bins setups by score/grade and measures:

- sample count;
- next 1/3/6/12/24 bar returns;
- MFE and MAE;
- stop-first vs target-first outcomes;
- expectancy in R;
- win rate;
- profit factor;
- drawdown contribution;
- calibration slope/reliability if probability-like mapping is attempted;
- results by instrument, timeframe, RTH/ETH, volatility regime, and direction.

Only if reliability/calibration passes the promotion gates may the UI relabel the number as a probability estimate.

## 13. Execution and exit architecture

MAX separates fast and endurance concepts instead of forcing one lifecycle onto all trades.

### 13.1 Fast horizon

Suitable for setups whose empirical edge is concentrated in the first few bars. Uses tighter time-stop logic and direct structural/ATR targets.

### 13.2 Endurance horizon

Suitable for setups whose value appears after extended holding. May use:

- structural stop floor;
- ATR noise floor;
- Kalman/filtered trail;
- opposite higher-timeframe range edge;
- runner logic.

### 13.3 Worst-case intrabar fills

Backtest logic must use conservative same-bar ordering where stop and target are both touched unless a lower-timeframe path conclusively resolves order. Gap-through logic fills no better than the available opening price.

### 13.4 Real-price execution

Transformed candles never provide executable fill prices in MAX production/backtest mode.

## 14. Legacy shadow benchmark

Compare mode must persist per-opportunity differences between Legacy and MAX:

- both accepted;
- Legacy-only;
- MAX-only;
- both rejected;
- direction disagreement;
- score difference;
- entry timing difference;
- stop/target geometry difference;
- realized outcome difference.

This prevents subjective visual preference from deciding whether MAX is better.

## 15. Visualization contract

Visuals must distinguish:

- pool type;
- pool state;
- origin vs knowledge time when diagnostics are enabled;
- sweep direction;
- grade/conviction;
- hard-veto reason when debug mode is enabled;
- proxy vs true-data concepts.

Historical drawings that extend backward to an origin bar are diagnostic only and visually marked as reconstructed.

MAX should reduce clutter by default: low-grade events may be suppressed while telemetry still records them.

## 16. Telemetry contract

Pine alerts emit versioned JSON. Minimum fields:

- schema version;
- MAX build/version hash;
- ticker / exchange / instrument profile;
- chart timeframe;
- event time;
- mode (`Legacy`, `MAX`, `Compare`);
- direction;
- trigger pool class;
- pool level and normalized penetration;
- reclaim age;
- sweep-quality components;
- long score;
- short score;
- component scores;
- volatility state;
- CVD/flow proxy state;
- target room;
- stop/target geometry;
- grade;
- veto reason;
- whether any field is a proxy;
- causality/debug flags.

Telemetry is research input only. It must contain no secrets and must not claim production authorization.

## 17. Offline validation and promotion gates

No MAX mechanism or coefficient is promoted from ICARUS research merely because it has positive P&L.

Minimum promotion path:

1. provenance and integrity pass;
2. causal timestamp audit;
3. sufficient sample size;
4. TUNE performance threshold defined before HOLD is inspected;
5. multiple-testing correction for searched variants;
6. HOLD performance positive after realistic costs;
7. stress-cost survival;
8. parameter-neighbor stability;
9. regime/time stability where sample permits;
10. comparison against the Legacy baseline and the current MAX baseline;
11. forward/shadow evidence before production-like labeling;
12. explicit version bump and changelog entry.

Synthetic tapes may test mechanics and robustness but cannot qualify an alpha parameter for MAX.

## 18. Explicitly excluded evidence

The following findings must not be promoted as validated MAX alpha without new real-data validation:

- large win-rate optimizer results originating from synthetic tapes;
- real-data results that failed permutation/null testing;
- ICARUS candidates marked rejected by the CL lab;
- walk-forward ML families that failed their registered gates;
- Heikin-Ashi fill artifacts;
- unadjusted continuous-futures results when roll discontinuities contaminate features;
- depth-derived signals that have not demonstrated incremental value over Pine-visible proxies.

## 19. Test architecture

Implementation must be test-led. Required test categories:

### 19.1 Static/source tests

- Legacy source checksum/reference unchanged;
- no decision path reads reconstructed-origin-only state;
- instrument profiles contain no accidental cross-market hardcoded price floors;
- telemetry schema fields are present and versioned;
- prohibited terms/claims such as live MBO when only proxies are available are absent.

### 19.2 Pine parity fixtures

Python-side fixtures reproduce MAX formulas from deterministic OHLCV sequences and compare expected:

- pivot knowledge time;
- BOS/CHoCH state;
- pool lifecycle;
- sweep state transitions;
- sweep-quality components;
- volatility fitness;
- CVD proxy;
- long/short score isolation;
- target-room calculation;
- stop/target geometry.

### 19.3 Causality tests

- prefix invariance: appending future bars cannot change prior MAX decisions;
- garbage-after-cut invariance for lower/higher-timeframe helpers;
- delayed pivot confirmation test;
- transformed-chart standard-price fill test;
- session-roll test;
- explicit leaky positive control that the harness must detect.

### 19.4 Regression tests

Representative NQ/MNQ and SI fixtures verify that:

- Legacy results remain unchanged;
- MAX no longer applies a one-price-unit Market Profile floor to Silver;
- NQ-specific priors are inactive outside NQ-family profiles;
- long and short evidence do not share mutable scoring state.

### 19.5 Research acceptance tests

Every proposed ICARUS-derived coefficient must ship with a compact machine-readable evidence receipt recording dataset, period, sample count, costs, test family, holdout result, and status (`EXPERIMENTAL`, `REJECTED`, `SHADOW`, `PROMOTED`).

## 20. Delivery phases

### Phase 0 — Baseline freeze

- identify and checksum the exact user Pine source used as Legacy;
- preserve it unchanged;
- create MAX namespace/version constants;
- create test fixtures and comparison harness.

### Phase 1 — Causal kernel + instrument profiles

- standard-price source;
- session/time kernel;
- instrument auto/profile layer;
- pivot origin vs knowledge time;
- removal/isolation of NQ-only assumptions from MAX.

### Phase 2 — Structure + liquidity map

- causal swings;
- BOS/CHoCH state;
- multi-pool map;
- equal-level clustering;
- pending penetration/reclaim state machine;
- sweep quality;
- target-room engine.

### Phase 3 — Volatility + microstructure proxies

- volatility permission/fitness;
- CVD/delta/absorption/divergence proxies;
- lower-timeframe intrabar features;
- explicit proxy metadata.

### Phase 4 — MAX scoring + grading

- independent long/short evidence;
- sweep-originated trigger architecture;
- hard vetoes vs soft score;
- grade/score visualization;
- Legacy-vs-MAX comparison telemetry.

### Phase 5 — Execution/exit evolution

- fast vs endurance lifecycle;
- conservative same-bar fill logic;
- structural/ATR stops;
- filtered trail and HTF endurance target where enabled;
- standard-price fills.

### Phase 6 — ICARUS research bridge

- versioned JSON alert telemetry;
- offline ingestion contract;
- Databento teacher experiments;
- evidence receipts;
- promotion pipeline.

### Phase 7 — Validation / release candidate

- Pine compile validation;
- deterministic fixture pass;
- causality pass;
- Legacy regression pass;
- SI and NQ/MNQ comparison runs;
- no unresolved high-severity discrepancies;
- release notes enumerate every behavior change.

## 21. Success criteria

MAX is successful only when all of the following are true:

1. Legacy remains reproducible and separately selectable.
2. MAX runs causally on historical and realtime bars without using future pivot or HTF knowledge.
3. Silver and other non-NQ markets no longer inherit NQ price-unit assumptions.
4. Sweep visualization reflects a multi-state liquidity model rather than a one-candle/latest-pivot shortcut.
5. Long and short evidence are independently computed.
6. TradingView order-flow displays are explicitly proxy-labeled unless the runtime genuinely provides aggressor data.
7. MAX telemetry can be ingested and evaluated offline without manual interpretation.
8. No synthetic-only, rejected, or artifact result is presented as validated alpha.
9. Compare mode can quantify whether MAX improves or degrades Legacy on unseen data.
10. Any promoted ICARUS-derived rule has a reproducible evidence receipt and forward/shadow validation status.

## 22. Out of scope for the first implementation

- direct live Databento access from Pine;
- self-modifying Pine code;
- automatic trading authorization;
- cloud-hosted model inference from Pine;
- treating the current empty ICARUS champion registry as if it contained validated strategies;
- copying all ICARUS features simply because they exist.

## 23. Review decision required before implementation plan

This document freezes the architecture. After user review/approval, the next artifact is the implementation plan generated from this specification. Product-code changes begin only after that plan is approved for execution.