# ICARUS Account Hybrid Loop Fabric v1

## Purpose

This fabric makes ChatGPT automations and GitHub Actions complementary rather than competing schedulers.

- **GitHub Actions owns durable orchestration:** immutable work requests, request identity, cadence, backfill detection, durable state, verification, audit history, and recovery metadata.
- **ChatGPT owns cognition:** research, reasoning, external/tool use, evidence reconciliation, hypothesis generation, quantitative analysis, architecture judgment, and task-specific decisions.
- Existing GitHub-native v3 liveness receipts remain useful, but **never count as substantive ChatGPT work** unless a matching hybrid result receipt proves the cognition lane completed the exact request.

Trading/deployment/publication authority remains false unless the user separately and explicitly changes it.

## Namespaces

- Registry: `automation_intelligence/hybrid_loop_fabric_v1/registry.json`
- Requests: `automation_intelligence/hybrid_loop_fabric_v1/requests/<lane>/<request_id>.json`
- Latest request pointer: `automation_intelligence/hybrid_loop_fabric_v1/requests/<lane>/latest.json`
- Results: `automation_intelligence/hybrid_loop_fabric_v1/results/<lane>/<request_id>.json`
- Health: `automation_intelligence/hybrid_loop_fabric_v1/health/<lane>.json`
- Existing substantive research receipts remain under `automation_intelligence/mcp_interface/research_runs/<lane>/` where that lane already uses them.
- Existing material MCP/Automation events remain under `automation_intelligence/mcp_interface/events/`.

## GitHub request contract

Every request is immutable and contains at minimum:

- `schema_version=icarus-hybrid-work-request-v1`
- `fabric_id`
- `request_id`
- `lane`
- `title`
- `automation_id`
- `requested_at_utc`
- `request_origin`
- `workflow_run_id`
- `workflow_run_attempt`
- `contract_fingerprint`
- `required_result_path`
- `prior_unresolved_request_ids`
- `execution_authorized=false`

A request does **not** claim that research or inference happened.

## ChatGPT worker contract

At the start of a hybrid run, the ChatGPT automation must:

1. Read `registry.json` and verify its lane title/automation_id.
2. Read `requests/<lane>/latest.json`.
3. Scan the bounded unresolved backlog surfaced by the request/health state.
4. Prefer the **oldest unresolved request first** so connector outages or scheduler misses are naturally backfilled.
5. Read the lane's existing durable research receipt/evidence state before claiming learning or change.
6. Perform the lane's original substantive mandate. The hybrid layer does not weaken, replace, summarize away, or silently mutate the original task contract.
7. Preserve provenance, temporal integrity, evidence limitations, and all lane-specific safety/authority invariants.
8. Never call a liveness heartbeat, GitHub request, scheduler timestamp, or deterministic placeholder substantive research.

When work for a request finishes, create exactly one immutable result file at the request's `required_result_path`.

## Result contract

Minimum fields:

- `schema_version=icarus-hybrid-work-result-v1`
- `fabric_id=icarus-account-hybrid-loop-fabric-v1`
- `request_id`
- `lane`
- `automation_id`
- `started_at_utc`
- `completed_at_utc`
- `outcome=MATERIAL_DELTA|NO_MATERIAL_DELTA|BLOCKED`
- `substantive_work_performed` (truthful boolean)
- `summary`
- `research_receipt_paths` (array)
- `event_paths` (array)
- `evidence` (actual sources/repository objects/tool outputs as applicable)
- `blockers` (array)
- `backfilled_request_ids` (array)
- `execution_authorized=false`

The worker must fetch the exact result file back from `main` and compare it with the intended payload. Only exact read-back permits `HYBRID_RESULT=VERIFIED`.

If write/read-back is unavailable or mismatched, the ChatGPT run must say `HYBRID_RESULT=FAILED` or `UNVERIFIED`, include the unsaved result payload in its report when possible, and never claim completion.

## Backfill contract

GitHub keeps unresolved requests visible until a matching result exists.

ChatGPT workers must:
- process the oldest unresolved request first;
- preserve the original request_id and provenance;
- never fabricate the work that would have occurred during an outage;
- label recovered work with actual recovery time;
- leave a request unresolved if the substantive task cannot be honestly reconstructed;
- process more than one request in a run only when the task can still be completed and verified within the run.

The default bounded scan is the most recent 24 request files for the lane. Historical backlog older than that is not deleted; it is simply outside the default hot scan and may be reconciled manually or by a deeper recovery run.

## Scheduling

Active GitHub dispatch lanes:

- OMEGA: minute :00
- Macro: :12
- Flow: :24
- AION: :36
- DAEDALUS: :48

The corresponding ChatGPT automations should run **five minutes later** (:05, :17, :29, :41, :53) to give GitHub time to persist the request first. This separation prevents the common race where the AI task wakes before its durable request exists.

Historical lanes remain registered but disabled. They are hybrid-ready for manual dispatch or later reactivation without being silently re-enabled.

## Failure semantics

- GitHub request exists, no result: `PENDING` or `OVERDUE`, never success.
- Result exists but request_id/lane/automation_id mismatch: `INVALID_RESULT`.
- Deterministic v3 liveness exists but hybrid result does not: `LIVENESS_ONLY`.
- ChatGPT work exists only in conversation output and was not persisted/read back: `UNVERIFIED`.
- Connector outage: retain request and retry/backfill later.
- Concurrent main movement: rebase only when safe; never resolve content conflicts by silently overwriting another writer.
- Duplicate request/result IDs: fail closed; immutable IDs must not be overwritten.

## Historical lane policy

The registry preserves every account loop with continuing architectural/research value. Explicitly retired/superseded canaries are excluded from active hybridization, but their prior repository evidence remains historical evidence. Disabled historical lanes are not automatically restarted.

## Non-negotiable invariants

- No fabricated plugins, sources, tests, commits, results, timestamps, backfills, or research.
- No claim of self-learning without durable before/after evidence.
- No silent strategy retuning.
- No live trading authority.
- No deployment/publication/force-push/destructive repository action unless separately authorized.
- Repository evidence outranks summaries where they conflict.
- A GitHub Action is infrastructure, not cognition.
- A ChatGPT automation is cognition, not a substitute for durable infrastructure.

## Historical executor

Historical lanes are not silently re-enabled. The former retired connection-canary automation slot `6abb1db46b308191ba1a27f13a42e745` is repurposed as **Historical Hybrid Executor (inactive)** and remains disabled.

When intentionally enabled, it:
- accepts only manual GitHub requests for registry lanes marked `HISTORICAL_DISABLED`;
- resolves the exact original paused ChatGPT automation by `automation_id` and uses that task prompt as the primary execution contract;
- uses the registry mandate only as a durable index/fallback, not as permission to discard detailed original instructions;
- writes the same immutable hybrid result schema and read-back verifies it;
- never enables the original paused task or mutates scheduler topology unless the user explicitly authorizes that exact mutation.

This preserves the full dormant prompts while giving every valuable historical lane a GitHub↔ChatGPT execution path.

