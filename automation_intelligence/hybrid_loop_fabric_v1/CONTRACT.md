# ICARUS Account-Wide Hybrid Loop Fabric v1.1

## Authority split

GitHub Actions is durable infrastructure. ChatGPT automations are cognition.

GitHub owns durable scheduling requests, immutable request identity, persistent state/checkpoints, unresolved/backlog visibility, failure detection, historical backfill bookkeeping, result reconciliation, audit history, concurrency protection and repository-native evidence.

ChatGPT owns reasoning, research, analysis, scientific judgment, hypothesis generation, evidence reconciliation, plugin/tool use, code/architecture judgment, model-assisted synthesis and task-specific cognition.

A GitHub Action, heartbeat, enabled flag, scheduler timestamp or deterministic receipt is **liveness only** unless a valid matching ChatGPT hybrid result proves that the exact request was substantively processed.

`execution_authorized=false` is invariant. This fabric grants no trading, broker/order, deployment, publication, credential or force-push authority.

## Canonical paths

- Registry: `automation_intelligence/hybrid_loop_fabric_v1/registry.json`
- Contract: `automation_intelligence/hybrid_loop_fabric_v1/CONTRACT.md`
- Requests: `automation_intelligence/hybrid_loop_fabric_v1/requests/<lane>/<request_id>.json`
- Latest request pointer: `automation_intelligence/hybrid_loop_fabric_v1/requests/<lane>/latest.json`
- Results: `automation_intelligence/hybrid_loop_fabric_v1/results/<lane>/<request_id>.json`
- Health: `automation_intelligence/hybrid_loop_fabric_v1/health/<lane>.json`
- Prompt snapshots: `automation_intelligence/hybrid_loop_fabric_v1/contracts/`
- Existing domain receipts/events remain authoritative in their existing lane/project namespaces and are referenced by the hybrid result rather than replaced.

## Request contract

Every immutable request uses `schema_version=icarus-hybrid-work-request-v1` and contains:

- `fabric_id`
- `request_id`
- `lane`
- `title`
- `automation_id`
- `project_scope`
- `requested_at_utc`
- `request_origin`
- `workflow_run_id`
- `workflow_run_attempt`
- `contract_fingerprint`
- `contract_registry_path`
- `required_result_path`
- `prior_unresolved_request_ids`
- `backfill_policy`
- `substantive_ai_inference_required=true`
- `github_liveness_receipt_is_not_completion=true`
- `execution_authorized=false`

The immutable request file is never overwritten. `latest.json` is only a mutable convenience pointer.

## Completion rule

A GitHub request is **NOT complete merely because GitHub Actions ran**.

A substantive request is complete only when all of the following are true:

1. an immutable result exists at the request's exact `required_result_path`;
2. the result uses `schema_version=icarus-hybrid-work-result-v1`;
3. `fabric_id`, `request_id`, `lane` and `automation_id` match the request exactly;
4. `outcome` is one of `MATERIAL_DELTA`, `NO_MATERIAL_DELTA`, `BLOCKED`;
5. all required result fields are present and `execution_authorized=false`;
6. the ChatGPT worker fetched the target-branch result back and compared it to the intended payload;
7. only exact read-back permits `HYBRID_RESULT=VERIFIED`.

Write-attempt-only is `UNVERIFIED` or `FAILED`, never complete.

## Hybrid request precedence over stabilization-only exits

When a valid unresolved hybrid request exists for the exact lane and automation_id, the hybrid request is the substantive unit of work.

Any preserved stabilization-only instruction that says **STOP**, **already complete**, **substantive work remains deferred**, **no research**, **no provider work**, **no corpus work**, or **no history/evidence work** is historical liveness behavior only and MUST NOT terminate the hybrid request.

If the lane's legacy heartbeat/finalization for the current scheduler slot is already `RUN_PERSISTED` with `completion_semantics=DURABILITY_RECEIPT_ONLY`, treat that as **durability prerequisite satisfied** and continue immediately to the lane's substantive mandate and exact hybrid result contract. A durability-only receipt is never substantive completion.

Safety, provenance, privacy, licensing, ownership/collision, branch, holdout, persistence/read-back and `execution_authorized=false` rules remain fully binding.

For time-sensitive collection lanes, do not fabricate a point-in-time observation for an older missed slot. If the oldest unresolved request cannot be honestly reconstructed, write a truthful `BLOCKED` result for that exact request_id with the recovery-time evidence and blocker, verify it by read-back, then process the next unresolved request only if time/budget permits.

## ChatGPT worker runtime

For every ACTIVE hybrid worker:

1. fetch `registry.json` and this contract;
2. verify exact lane, title, automation_id, repository and branch;
3. fetch the lane's `requests/<lane>/latest.json`;
4. inspect unresolved requests from the hot window, preserving all older requests durably;
5. select the **oldest unresolved request first**;
6. perform the lane's preserved substantive mandate, not a heartbeat placeholder;
7. preserve existing lane-specific receipts, histories, ledgers, MCP events, state capsules and evidence;
8. create exactly one immutable hybrid result for each completed request;
9. fetch that result back from the target branch and compare it exactly;
10. refuse false success if persistence or read-back cannot be proven.

The worker may process the newest request after an older unresolved request only when time/budget still permits truthful substantive work and verified persistence.

## Result contract

Every immutable result uses `schema_version=icarus-hybrid-work-result-v1` and contains:

- `fabric_id`
- `request_id`
- `lane`
- `automation_id`
- `started_at_utc`
- `completed_at_utc`
- `outcome`
- `substantive_work_performed`
- `summary`
- `evidence`
- `research_receipt_paths`
- `event_paths`
- `blockers`
- `backfilled_request_ids`
- `execution_authorized=false`

A result is an orchestration/completion proof. It never replaces substantive domain evidence.

## Backfill and outages

- Retain every request ID.
- Default hot scan: 24 most recent immutable requests per lane.
- Process oldest unresolved first.
- Preserve original request provenance and separately record actual recovery time.
- Never fabricate work that supposedly occurred during an outage.
- Reconstruct only what current evidence supports.
- Irrecoverable work remains unresolved or is closed with truthful `outcome=BLOCKED`; no synthetic history is manufactured.
- Failed and missed history is never erased.

## Active cutover schedule

The live scheduler observed during the migration has four enabled valuable lanes. Their native ChatGPT cadence remains hourly at:

- Robustness Guardian Evolution: :05 America/Chicago
- Advanced CSV Data Collector: :15
- Alpha Synthesis Evolution: :25
- Microstructure Sensor Grid: :35

GitHub dispatches exactly five minutes earlier:

- Robustness Guardian Evolution: :00
- Advanced CSV Data Collector: :10
- Alpha Synthesis Evolution: :20
- Microstructure Sensor Grid: :30

Because these are every-hour schedules, UTC GitHub cron minute values remain the same minute through DST transitions.

## Active mandate recovery

The four enabled prompts at migration time were stabilization/liveness contracts that explicitly deferred substantive work. Their exact pre-cutover prompts are snapshotted under `contracts/active_originals/`.

Each active worker is also bound to the richer disabled predecessor contract for the same lane. The hybrid runtime supersedes only stabilization clauses that prohibit substantive work; it does **not** weaken safety, authority, provenance, persistence, repository ownership, collision or verification gates.

## Historical lanes

Disabled/paused valuable tasks are registered as `HISTORICAL_DISABLED` and remain disabled. They are dispatched manually, one lane at a time, through GitHub.

A historical request must have `request_origin=GITHUB_ACTIONS_MANUAL`. The Historical Hybrid Executor resolves the exact original paused automation by automation_id/title and obeys that detailed prompt as primary contract. It never enables the original task.

Repository-only historical mandates from the superseded hybrid registry are retained separately and are never misrepresented as current scheduler records.

## Historical Hybrid Executor

The only clearly disposable disabled slot identified during this migration is automation `6abda2dc3aa881919b80fa89f1c5122e`, an exact duplicate stabilization Alpha task with no recorded run and no unique substantive mandate. Its pre-repurpose prompt is snapshotted before reuse.

The repurposed executor remains **disabled**. When intentionally enabled it:

- accepts only manually dispatched historical requests;
- handles one historical lane at a time;
- resolves the original task by automation_id/title when exposed;
- uses the registry mandate only as an index/fallback;
- writes and exact-readback-verifies the normal immutable hybrid result;
- never automatically enables the original paused automation;
- never grants execution authority.

## Existing specialist persistence and liveness planes

Existing durability/watchdog/native-liveness workflows and lane-specific persistence remain preserved. Deterministic liveness receipts remain distinct from substantive ChatGPT research.

Hybrid results reference existing research receipts, MCP events, audit receipts, brain-feed objects, experiment ledgers, agent state and evidence records rather than replacing them.

## Concurrency and write safety

The bridge workflow:

- grants `contents: write` only;
- stages only `automation_intelligence/hybrid_loop_fabric_v1/requests` and `health`;
- uses immutable request filenames;
- uses safe Actions concurrency without canceling an in-progress writer;
- fetches/rebases before push and retries ordinary concurrent-main movement;
- never force-pushes;
- aborts on semantic/rebase conflict rather than silently resolving it;
- uses `[skip ci]` for request commits to avoid recursive workflow storms.

## Non-negotiable invariants

Never fabricate tool/plugin execution, research, tests, commits, workflow results, timestamps, backfills, model inference or evidence.

Never claim self-learning without durable before/after evidence.

Never count a heartbeat, task last_run_time or enabled flag as successful substantive work.

Do not authorize live trading.

Do not authorize deployment/publication/force-push/destructive repository changes unless separately and explicitly authorized.

Preserve provenance and existing specialist persistence.
