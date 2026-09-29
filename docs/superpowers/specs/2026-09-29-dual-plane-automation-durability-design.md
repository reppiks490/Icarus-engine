# Dual-Plane Automation Durability Design

Date: 2026-09-29
Status: DESIGN — approved in conversation; implementation requires separate plan approval
Repository: `reppiks490/Icarus-engine`

## 1. Intent

Make the five authoritative ICARUS automation lanes durable even when a ChatGPT scheduled invocation triggers but fails to execute its GitHub connector action.

The system must preserve the AI loops and their existing staggered hourly cadence while removing the ChatGPT-scheduler-to-GitHub connector hop as a single point of silent persistence failure.

Success means:

- the five ChatGPT automations remain the AI/reasoning plane;
- GitHub provides an independent watchdog and backlog plane;
- every expected lane slot becomes auditable as either a verified natural receipt or an immutable missing-run incident;
- no fallback mechanism may fabricate a ChatGPT `NATURAL_SCHEDULE` receipt;
- missed slots survive connector or scheduler outages and can be recovered later;
- scheduler topology remains externally managed and cannot self-mutate from a lane run.

## 2. Evidence motivating the change

Observed on 2026-09-29:

- all five scheduler entries were enabled and triggering;
- GitHub write permission works from the interactive ChatGPT connector;
- the GitHub app-specific permission mode is `Allow all actions`;
- a manual one-call `create_file` canary reached GitHub;
- at least one natural AION v4.3 liveness receipt reached GitHub;
- later post-r10 natural invocations for AION, DAEDALUS, OMEGA, and Macro completed without any GitHub commit or immutable run receipt;
- repeated prompt-order/compactness changes therefore did not eliminate the failure.

Conclusion: the remaining fault boundary is the unattended ChatGPT scheduled-runtime -> connector-execution path. The design must not depend on prompt tuning alone.

## 3. Existing authoritative topology

Authoritative ChatGPT automation IDs:

| Lane | Automation ID | Nominal minute |
|---|---|---:|
| OMEGA | `6abb57443c0c81919676c71d87493353` | :00 |
| Macro | `6ab8174517b48191b67ac472205a28d3` | :12 |
| Flow | `6ab817544e68819197b5db21eb2cbe2b` | :24 |
| AION | `6abb1618be1c8191943f5d4e2d88978d` | :36 |
| DAEDALUS | `6ab8177918b48191a97e56c44b57d2c5` | :48 |

Timezone: `America/Chicago`.

Authoritative operational state branch: `automation/omega-native-v2`.

Authoritative namespace: `automation_intelligence/omega_stack_native_v2`.

Current persistence protocol: `omega-stack-persistence-v4.3-append-first`.

Important repository fact: the copy of `automation_intelligence/omega_stack_native_v2/control_plane.json` on `main` is stale and contains superseded IDs/protocol values. The watchdog must never use that stale copy as scheduler truth.

## 4. Architecture

### 4.1 Plane A — ChatGPT AI plane

The existing five ChatGPT automations remain enabled and keep their schedules unchanged:

- OMEGA :00
- Macro :12
- Flow :24
- AION :36
- DAEDALUS :48

Each lane continues to attempt its v4.3 immutable natural liveness receipt first:

`automation_intelligence/omega_stack_native_v2/<lane>/runs/<RUN_ID>.json`

A valid natural receipt must preserve:

- exact authoritative automation ID;
- `CONTROL_PLANE_ID=omega-aion-daedalus-native-v2`;
- `persistence_protocol_version=omega-stack-persistence-v4.3-append-first`;
- `RUN_STATUS=RUN_PERSISTED`;
- `FINALIZATION_STATUS=LIVENESS_VERIFIED`;
- `verification_method=GITHUB_CREATE_FILE_RESPONSE`;
- `run_origin=NATURAL_SCHEDULE`;
- nominal `scheduled_for`;
- actual `started_at_utc`;
- `execution_authorized=false`.

The AI plane remains the only plane allowed to label a run `NATURAL_SCHEDULE`.

### 4.2 Plane B — GitHub durability/watchdog plane

Add a scheduled GitHub Actions workflow on the default branch `main`.

Proposed workflow:

`.github/workflows/automation-durability-watchdog.yml`

Proposed implementation module:

`tools/automation_durability_watchdog.py`

The workflow definition lives on `main` because scheduled GitHub Actions execute from the default branch. The job itself checks out `automation/omega-native-v2`, reads the authoritative r10-or-newer control plane there, evaluates expected slots, writes reconciliation artifacts to that same branch, then pushes only those artifacts.

The watchdog is not an AI worker. It performs deterministic liveness accounting only.

## 5. Scheduling and grace policy

Run the watchdog every five minutes.

For each lane, compute expected nominal slots from the authoritative lane minute and `America/Chicago`.

A slot is eligible for missing-run adjudication only after a configurable grace period.

Initial grace:

`WATCHDOG_GRACE_MINUTES=12`

Reason:

- the current ChatGPT scheduler already tolerates approximately +/-6 minutes of start jitter;
- the extra margin prevents false incidents caused by scheduler transport delay or GitHub commit propagation.

Each watchdog invocation evaluates at least the previous 48 hours. This rolling horizon gives automatic historical backfill after temporary workflow outages without requiring a mutable cursor.

All calculations must be timezone-aware using Python standard-library `zoneinfo`; DST transitions must be tested explicitly.

## 6. Natural-receipt validation

For each expected slot, search the lane's immutable `runs/` receipts on `automation/omega-native-v2`.

A receipt satisfies the slot only when all material identity fields match:

- lane name;
- authoritative automation ID;
- control-plane ID;
- v4.3 protocol;
- `run_origin=NATURAL_SCHEDULE`;
- `RUN_STATUS=RUN_PERSISTED`;
- `FINALIZATION_STATUS=LIVENESS_VERIFIED`;
- nominal `scheduled_for` equals the expected slot;
- actual start is within the accepted scheduler-jitter policy, unless a later control-plane revision explicitly changes that policy.

Malformed, foreign-ID, wrong-protocol, wrong-origin, or cross-slot receipts do not satisfy liveness.

The watchdog must never repair or overwrite a natural receipt.

## 7. Missing-run incident ledger

If no valid natural receipt exists after the grace period, create an immutable incident:

`automation_intelligence/omega_stack_native_v2/reconciliation/missed/<lane>/<SLOT_ID>.json`

where `SLOT_ID` is a canonical UTC representation of the expected nominal slot.

Required fields:

- `kind=CHATGPT_NATURAL_RECEIPT_MISSING`;
- lane;
- expected automation ID;
- control-plane ID;
- protocol expected;
- nominal slot in Chicago time;
- canonical slot UTC;
- adjudicated_at_utc;
- grace_minutes;
- evidence checked;
- `natural_receipt_found=false`;
- `fallback_origin=GITHUB_WATCHDOG`;
- `scheduler_evidence_status=UNKNOWN` unless independently available;
- `execution_authorized=false`;
- deterministic schema/version.

These files are incident evidence only. They are not run receipts and may not contain `run_origin=NATURAL_SCHEDULE`.

Path identity makes incident creation idempotent: if the file already exists, the watchdog leaves it unchanged.

## 8. Durable recovery backlog

Every missing incident also implies one unresolved recovery item.

Canonical backlog artifact:

`automation_intelligence/omega_stack_native_v2/reconciliation/backlog/<lane>/<SLOT_ID>.json`

Required status:

`RECOVERY_PENDING_AI`

The backlog records what was missed, not invented work output.

A future successful ChatGPT lane may process at most one oldest unresolved backlog item after its own natural liveness receipt has been durably created.

Recovery must be explicit and provenance-separated:

`automation_intelligence/omega_stack_native_v2/reconciliation/recovered/<lane>/<SLOT_ID>/<RECOVERY_RUN_ID>.json`

A recovery artifact must state:

- original missed slot;
- original incident path;
- recovery run ID;
- recovery timestamp;
- source data actually available;
- what could and could not be reconstructed;
- `run_origin=BACKFILL_RECOVERY`, never `NATURAL_SCHEDULE`;
- truthful data gaps and conflicts.

Historical market/event reconstruction must use only lawful public/licensed data actually available at recovery time. No field may be represented as observed-at-slot unless its source provides valid historical point-in-time data.

## 9. Late-arrival reconciliation

If a valid natural receipt appears after a missing incident was already created, preserve both facts.

Do not delete or rewrite the incident.

Create:

`automation_intelligence/omega_stack_native_v2/reconciliation/late_arrival/<lane>/<SLOT_ID>.json`

with:

- incident reference;
- natural receipt reference;
- observed-at timestamp;
- classification `LATE_NATURAL_RECEIPT_AFTER_INCIDENT`.

This keeps the audit trail append-only.

## 10. Watchdog health records

The watchdog itself needs liveness without creating noisy commits every five minutes.

Use GitHub Actions run status as primary watchdog-execution evidence.

Repository writes occur only for state transitions:

- new missing incident;
- new backlog item;
- late-arrival reconciliation;
- optional recovery-resolution artifact.

No heartbeat commit is required on every watchdog invocation.

A workflow failure is visible through GitHub Actions and must not be disguised as a successful watchdog cycle.

## 11. Workflow permissions and safety

Workflow-level permissions:

`contents: write`

No deployment, release, issue, PR, package, secret, environment, or trading permissions are required.

The workflow must:

- check out the exact target branch `automation/omega-native-v2`;
- fail closed if the authoritative control plane is absent, malformed, or inconsistent;
- refuse to write outside `automation_intelligence/omega_stack_native_v2/reconciliation/`;
- refuse to write natural `runs/` or `work/` receipts;
- keep `execution_authorized=false`;
- use a concurrency group so two watchdog runs cannot race;
- use deterministic serialization and stable paths;
- never force-push;
- never rewrite scheduler configuration.

If repository or branch policy prevents `GITHUB_TOKEN` from pushing the reconciliation artifacts, the workflow must fail visibly rather than falling back to another credential silently.

## 12. ChatGPT prompt changes after watchdog deployment

Only after the watchdog path itself is implemented and verified:

1. retain first-action natural liveness persistence;
2. after successful natural liveness, permit one bounded backlog lookup;
3. process at most one oldest unresolved item when useful;
4. emit an immutable `BACKFILL_RECOVERY` artifact;
5. never convert backlog evidence into a fabricated natural receipt;
6. preserve current protected-infrastructure/no-self-disable rules.

The hourly cadence and automation IDs remain unchanged.

## 13. Control-plane evolution

The authoritative control plane on `automation/omega-native-v2` should move to a new revision after implementation, for example r11, containing:

- dual-plane architecture enabled;
- watchdog workflow path;
- watchdog schema version;
- grace minutes;
- rolling reconciliation horizon;
- reconciliation namespace;
- strict origin taxonomy:
  - `NATURAL_SCHEDULE`
  - `GITHUB_WATCHDOG`
  - `BACKFILL_RECOVERY`;
- rule that only ChatGPT natural runs may write `runs/`;
- rule that the watchdog only writes `reconciliation/`.

The stale `main` control-plane copy is not automatically promoted to authority by this design.

## 14. Testing strategy

### Unit tests

Add tests for the deterministic watchdog module covering:

1. valid natural receipt satisfies a slot;
2. no receipt before grace does not create an incident;
3. no receipt after grace creates one incident plus one backlog item;
4. repeat evaluation is idempotent;
5. wrong automation ID is rejected;
6. wrong control-plane ID is rejected;
7. wrong protocol is rejected;
8. wrong origin is rejected;
9. malformed JSON is rejected and recorded as evidence, not accepted;
10. receipt mapped to the wrong nominal slot is rejected;
11. late valid receipt produces a late-arrival record without deleting incident history;
12. 48-hour rolling evaluation reconstructs multiple missed slots;
13. DST fall-back ambiguity is canonicalized correctly;
14. DST spring-forward nonexistent local time cannot produce duplicate/invalid slots;
15. writer rejects paths outside the reconciliation namespace.

### Workflow validation

Before declaring deployment healthy:

- verify the workflow exists on `main`;
- verify it checks out `automation/omega-native-v2`;
- verify `contents: write` is the only elevated permission;
- observe a real GitHub Actions run;
- verify either a no-change success or a correctly scoped reconciliation commit;
- verify no natural receipt was fabricated by the watchdog.

### End-to-end acceptance

The architecture is accepted only after:

1. all five ChatGPT automations remain enabled with unchanged cadence;
2. GitHub watchdog executes successfully;
3. at least one known missing slot is represented by an immutable watchdog incident/backlog record, or a controlled test fixture proves the same path;
4. a valid natural receipt is never duplicated as an incident;
5. a simulated late arrival preserves both incident and late-arrival evidence;
6. the workflow cannot write outside reconciliation namespace;
7. one subsequent successful ChatGPT lane can consume one backlog item and write a `BACKFILL_RECOVERY` record without changing the historical natural-run truth.

## 15. Failure handling

### ChatGPT scheduler triggers but connector call disappears

Watchdog creates missing incident/backlog after grace.

### GitHub Actions delayed

Rolling 48-hour reconciliation catches missed slots on a later invocation.

### GitHub Actions cannot push

Workflow fails visibly; no alternate credential or fabricated success.

### Target branch unavailable

Fail closed. Do not switch silently to `main`.

### Control-plane identity drift

Fail closed and require explicit reconciliation.

### Duplicate watchdog invocation

Concurrency plus idempotent slot paths prevents duplicate state.

### Natural receipt arrives late

Create late-arrival evidence; do not erase incident history.

### Data source unavailable during recovery

Write truthful degraded recovery with explicit data gaps, or leave backlog unresolved.

## 16. Non-goals

This change does not:

- authorize live trading;
- merge or deploy strategy code;
- replace the five ChatGPT automations;
- claim GitHub Actions can reproduce AI reasoning;
- fabricate missing historical observations;
- reactivate retired loops;
- change the five hourly scheduler minutes;
- make stale `main` control-plane data authoritative;
- guarantee external platform uptime.

## 17. Pre-existing repository issues observed but out of scope

The `main` README currently contains unresolved merge-conflict markers and contradictory repository guidance. That should be repaired separately; this durability design must not silently broaden into a README cleanup.

The `main` copy of `omega_stack_native_v2/control_plane.json` is stale relative to the authoritative `automation/omega-native-v2` branch. The implementation must treat that divergence explicitly as described above rather than normalizing it incidentally.

## 18. Implementation surface

Expected files in the implementation phase:

- `.github/workflows/automation-durability-watchdog.yml` — new
- `tools/automation_durability_watchdog.py` — new
- `tests/test_automation_durability_watchdog.py` — new
- `automation_intelligence/omega_stack_native_v2/control_plane.json` on `automation/omega-native-v2` — update after watchdog verification
- `automation_intelligence/omega_stack_native_v2/persistence_contract.json` on `automation/omega-native-v2` — update after watchdog verification
- five ChatGPT automation prompts — update only after GitHub watchdog verification

Knowledge delta for this design phase: this specification is the canonical design record. No product/trading behavior is changed by the design-only commit.

## 19. Decision

Adopt the dual-plane architecture.

The ChatGPT scheduler remains the intelligence plane. GitHub Actions becomes the independent durability/reconciliation plane. Append-only provenance separates natural runs, watchdog incidents, and recovery work so failure can be repaired without rewriting history.
