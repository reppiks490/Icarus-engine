# Native five-lane research

User directive, 2026-10-07: keep recurring research, stop scheduled ChatGPT/Work usage. The five ChatGPT worker prompts and schedules are preserved in `automation_intelligence/token_budget_handoffs/20261007T204800Z_five_loop_pause.json`. They must not be automatically resumed to drain a backlog.

`native-five-research.yml` performs an hourly cycle at nominal minute 41, plus manual dispatch and code-change canaries. GitHub may delay cron; actual acquisition clocks are recorded. It requires no ChatGPT automation, API key or paid model transport. Runner usage is still subject to GitHub's account rules. No paid inference fallback exists.

## What actually runs

| Lane | Research measurement | Qualification limits |
|---|---|---|
| Flow | Public Coinbase/Kraken spot and available Bybit spot/linear completed hourly candles; separate 28-hour median/MAD range and volume anomalies; fresh/stale and cross-venue reconciliation | No aggressor flow, absorption, historic liquidity, or causal claim; USD and USDT identities kept separate |
| Macro | First-party Fed/ECB/BLS release feeds, dates and titles; public FRED daily 2-year/10-year yields and broad dollar index changes | No economic surprise without consensus; no daily series treated as intraday DXY or yields |
| AION | Fixed volume-outlier/next-hour-range hypothesis per representation, chronological 60/40 split, two-sample embargo and explicit minimum event counts | Descriptive OOS association only; overlapping rolling tests are not independent; no profitable strategy or reusable promotion holdout |
| DAEDALUS | Independently implemented scalar oracle for current Flow calculations, missing/contiguous baseline and completed-bar checks | Current-cycle statistics assurance, not certification of all repository claims |
| OMEGA | Reconcile four actual lane outcomes and expose blocking/degraded evidence | No automatic promotion or execution authority |

A pinned Qwen3 1.7B model is run locally on the GitHub runner, using the existing `tools.github_native_local_model.py` runtime. It selects one of three lane-specific, evidence-backed next-test questions when semantic state changes, generation was blocked, or the interpretation policy changes. Grammar permits only those questions, an exact selection marker and empty factual gap/conflict arrays; post-validation rejects invented facts. Scripts supply measurements and defects. Generation grammar pins the exact lane and false execution authority. Its text is always `UNVERIFIED_MODEL_INFERENCE`; it cannot replace measured facts, clear defects or issue orders. Model download or generation failures preserve measured research and remain explicit in every lane receipt. A small local model is not represented as equivalent to frontier research reasoning.

## Evidence and UI

Immutable run directories contain normalized input evidence and all five lane receipts under `automation_intelligence/native_research_v1/cycles/`. Each receipt identifies the source revision, input hash, prior receipt and any event path. Full input observations are persisted for replay, with per-provider acquisition intervals; repeated sources are not counted as independent provider families. The latest status document contains actual lane and model statuses, not a liveness substitute. Failed Git pushes retain an Actions artifact for 30 days; successful runs retain immutable evidence in Git.

A semantic change emits an `icarus-mcp-event-v1` event with the existing allowlisted lane source and full producer envelope. Existing MCP/Automation and revision-verified remote-sync consumers can read these; UI visibility still requires checkout synchronization or existing remote sync. Local model output is excluded from authoritative event findings. No canonical runtime code or strategy is changed.

## Operations and recovery

Run `python -m tools.native_research --root . --run-id <unique-safe-id>` for acquisition/measurement only. Add `--binary <llama-completion> --model <pinned-GGUF>` for local interpretation. Do not reuse IDs or overwrite immutable receipts. A subsequent run can acquire available historical candles after outages, but does not fabricate missed contemporaneous observations; the retrospective AION association and fresh current Flow state have different purposes. There is no claim of full historical coverage beyond each provider's returned window.

Run `python -m pytest tests/test_native_research.py tests/test_native_research_sources.py tests/test_github_native_local_model.py -q` for scoped verification. Negative controls cover future mutation, corrupt statistics, missing intervals, invalid candles and local runtime failure. Full repository tests remain independent of scheduled measured research.

Pause `native-five-research` in GitHub Actions to stop native execution; this does not reactivate ChatGPT. Review provider failures in the receipt before calling coverage healthy. Direct licensed futures, Twelve Data/other connector-only feeds and full scientific hypothesis generation remain gaps until lawful runnable adapters and entitlement evidence exist. Do not label a cron receipt as completed research.

## Decision and reversal conditions

Reuse existing local inference and MCP contracts rather than creating a competing brain or changing the shared other-account hybrid registry. This registry presently contains different identities, so it was intentionally left intact. The new workflow owns only `native_research_v1` and its own immutable MCP events. Reconsider the bounded local model if empirical quality measurements support a stronger runnable backend; never silently activate paid APIs. Research-only defaults and the user token-stop directive persist across handoffs.

Validation note: GitHub full-suite CI and the brain-federation contract passed on the installation commit. A repeated local full-suite run had two failures in `tests_engine/test_adaptation.py` (`test_restart_abandons_confirmed_dead_owner_without_replaying_interval` and `test_process_identity_is_stable_for_current_process`); both also fail on unchanged baseline fa4b34a5 in this sandbox, where `/proc/<current-pid>/stat` is absent. The first native run persisted five substantive measurement receipts but local responses failed validation. The follow-up pins the generated lane/authority and retries blocked generation; only read-back generation evidence qualifies interpretation as operational.

The second canary generated Flow/Macro interpretations; three other lanes reported transport failures. Native model inputs are therefore reduced to a bounded factual snapshot while full measurements remain in immutable receipts. Native output uses a 384-token budget and a short next-test instruction; other existing local-model callers retain their 768-token default. TIMEOUT, INVALID_JSON and RUNTIME_FAILURE are distinguished without exposing raw model text. Failed model generations remain retryable and never alter measurement qualification.

Grounding repair: canary 37688102334 produced valid JSON but some unsupported model statements. Those immutable interpretations remain historical, unverified outputs and must not be used as findings. The grounded-next-test-v1 policy replaces free-text interpretation with constrained test selection; measured evidence is unchanged.
