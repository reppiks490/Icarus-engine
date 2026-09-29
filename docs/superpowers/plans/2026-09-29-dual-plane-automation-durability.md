# Dual-Plane Automation Durability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub-native watchdog and reconciliation backlog that makes every expected ICARUS automation slot auditable without fabricating ChatGPT natural-run receipts.

**Architecture:** Keep the five ChatGPT automations as the intelligence plane and add a deterministic GitHub Actions durability plane. The workflow is defined on `main`, runs every five minutes, checks out `automation/omega-native-v2` into a separate working tree, validates natural v4.3 receipts, and writes only append-only reconciliation artifacts to that target branch. The watchdog never writes `runs/` or `work/` and never labels fallback evidence `NATURAL_SCHEDULE`.

**Tech Stack:** Python 3.11+ standard library (`dataclasses`, `datetime`, `json`, `pathlib`, `zoneinfo`), pytest, GitHub Actions, git.

**Spec:** `docs/superpowers/specs/2026-09-29-dual-plane-automation-durability-design.md`

## Global Constraints

- Preserve all five ChatGPT automation IDs and nominal minutes: OMEGA :00, Macro :12, Flow :24, AION :36, DAEDALUS :48.
- Preserve timezone `America/Chicago`.
- Preserve target branch `automation/omega-native-v2` and namespace `automation_intelligence/omega_stack_native_v2`.
- Preserve `CONTROL_PLANE_ID=omega-aion-daedalus-native-v2`.
- Preserve natural protocol `omega-stack-persistence-v4.3-append-first`.
- Preserve `execution_authorized=false`.
- Only ChatGPT natural runs may write `<lane>/runs/` and use `run_origin=NATURAL_SCHEDULE`.
- GitHub watchdog writes only beneath `automation_intelligence/omega_stack_native_v2/reconciliation/`.
- Watchdog grace is `12` minutes and rolling reconciliation horizon is `48` hours.
- Expected-slot generation starts no earlier than authoritative `identity_binding.bound_at_utc` when present; otherwise use `created_at_utc`.
- Scheduler jitter acceptance remains `+/-360` seconds unless the target-branch control plane says otherwise.
- No third-party runtime dependency is added to the watchdog.
- No force pushes, alternate hidden credentials, scheduler mutations, trading authorization, deployment, or fabricated historical observations.
- The stale `main` copy of the control plane is never used as scheduler truth.
- Root `README.md` merge-conflict cleanup is out of scope.

## Review Focus

1. **Portfolio start boundary:** a 48-hour scan must not create incidents for slots before the authoritative ID binding; Task 1 adds `test_expected_slots_clamp_to_identity_binding`.
2. **DST repeated/nonexistent hours:** expected-slot IDs must remain unique and UTC-canonical through America/Chicago fall-back and spring-forward; Task 1 adds both DST tests.
3. **Malformed/foreign receipts:** bad JSON, wrong automation ID, wrong control-plane ID, wrong protocol, wrong origin, or wrong slot must never satisfy liveness; Task 2 pins each case.
4. **Concurrent target-branch writes:** a rejected non-force push must fail visibly and be recoverable on the next five-minute run; Task 4 validates workflow behavior and prohibits force push.
5. **Watchdog provenance leakage:** no watchdog path or payload may write under `runs/`/`work/` or contain `run_origin=NATURAL_SCHEDULE`; Task 3 adds namespace and payload safety tests.

---

### Task 1: Authoritative topology and expected-slot model

**Files:**
- Create: `tools/automation_durability_watchdog.py`
- Create: `tests/test_automation_durability_watchdog.py`

**Interfaces:**
- Produces:
  - `LaneConfig(name: str, automation_id: str, minute: int, root: str)`
  - `WatchdogConfig(control_plane_id: str, protocol: str, timezone: str, authoritative_branch: str, namespace_root: str, identity_bound_at_utc: datetime, jitter_seconds: int, lanes: tuple[LaneConfig, ...])`
  - `ExpectedSlot(lane: LaneConfig, scheduled_local: datetime, scheduled_utc: datetime, slot_id: str)`
  - `load_watchdog_config(root: Path) -> WatchdogConfig`
  - `iter_expected_slots(config: WatchdogConfig, now_utc: datetime, horizon_hours: int = 48) -> list[ExpectedSlot]`

- [ ] **Step 1: Write failing configuration tests**

Add tests asserting that `load_watchdog_config()` reads only the target working tree's `automation_intelligence/omega_stack_native_v2/control_plane.json`, returns exactly the five authoritative IDs/minutes, requires `operational_state_branch == "automation/omega-native-v2"`, requires `persistence_protocol_version == "omega-stack-persistence-v4.3-append-first"`, and rejects inconsistent `active[]` versus `identity_binding.authoritative_ids`.

Run:

`pytest tests/test_automation_durability_watchdog.py -k "config" -v`

Expected: FAIL because the module/interfaces do not yet exist.

- [ ] **Step 2: Implement immutable topology parsing**

Implement the dataclasses and `load_watchdog_config(root)`. Fail closed with `ValueError` for missing/malformed control plane, wrong control-plane ID, wrong branch/protocol, non-five active lanes, duplicate minutes, unexpected lane names, or identity-binding mismatch.

- [ ] **Step 3: Write failing expected-slot tests**

Add:
- `test_expected_slots_clamp_to_identity_binding`
- `test_expected_slots_cover_each_lane_hourly`
- `test_expected_slots_use_canonical_utc_slot_ids`
- `test_dst_fall_back_produces_distinct_utc_slots`
- `test_dst_spring_forward_does_not_create_nonexistent_local_slots`

Expected slot ID format: `YYYYMMDDTHHMMSSZ` from `scheduled_utc`.

Generate candidate slots by iterating UTC time and converting to `America/Chicago`, not by constructing nonexistent local wall times.

Run:

`pytest tests/test_automation_durability_watchdog.py -k "expected_slots or dst" -v`

Expected: FAIL until slot generation exists.

- [ ] **Step 4: Implement slot generation**

Implement `iter_expected_slots(...)` with:
- start = max(`now_utc - horizon`, `identity_bound_at_utc`);
- minute match against each lane's configured minute after UTC -> local conversion;
- aware datetimes only;
- stable sort by `scheduled_utc`, then lane name;
- no slots newer than `now_utc`.

- [ ] **Step 5: Run Task 1 tests**

Run:

`pytest tests/test_automation_durability_watchdog.py -k "config or expected_slots or dst" -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/automation_durability_watchdog.py tests/test_automation_durability_watchdog.py
git commit -m "feat: model automation watchdog slots"
```

---

### Task 2: Natural-receipt validation and slot matching

**Files:**
- Modify: `tools/automation_durability_watchdog.py`
- Modify: `tests/test_automation_durability_watchdog.py`

**Interfaces:**
- Consumes: `WatchdogConfig`, `ExpectedSlot`
- Produces:
  - `ReceiptCheck(path: str, valid: bool, errors: tuple[str, ...], run_id: str | None)`
  - `ReceiptMatch(path: str, run_id: str, payload: dict[str, object])`
  - `scan_lane_receipts(root: Path, slot: ExpectedSlot, config: WatchdogConfig) -> tuple[ReceiptMatch | None, tuple[ReceiptCheck, ...]]`

- [ ] **Step 1: Add a fixture matching the observed real v4.3 schema**

Use the evidenced shape:
- `engine="aion"`
- `RUN_ID="aion-20260929T174025Z"`
- `RUN_STATUS="RUN_PERSISTED"`
- `FINALIZATION_STATUS="LIVENESS_VERIFIED"`
- `CONTROL_PLANE_ID="omega-aion-daedalus-native-v2"`
- correct automation ID
- protocol `omega-stack-persistence-v4.3-append-first`
- `scheduled_for="2026-09-29T12:36:00-05:00"`
- `started_at_utc="2026-09-29T17:40:25Z"`
- `execution_authorized=false`
- `verification_method="GITHUB_CREATE_FILE_RESPONSE"`
- `run_origin="NATURAL_SCHEDULE"`.

- [ ] **Step 2: Write failing validation tests**

Add tests:
- valid receipt satisfies the expected slot;
- wrong automation ID rejected;
- wrong control-plane ID rejected;
- wrong protocol rejected;
- wrong `run_origin` rejected;
- `execution_authorized=true` rejected;
- wrong `RUN_STATUS` or `FINALIZATION_STATUS` rejected;
- wrong `verification_method` rejected;
- malformed JSON rejected with a `ReceiptCheck` error;
- wrong nominal slot rejected;
- `started_at_utc` outside configured +/-360 seconds rejected;
- matching receipt within jitter accepted.

Run:

`pytest tests/test_automation_durability_watchdog.py -k "receipt" -v`

Expected: FAIL.

- [ ] **Step 3: Implement receipt parsing and exact validation**

Parse `scheduled_for` and `started_at_utc` as aware datetimes. Compare scheduled slot by UTC instant so offset formatting differences do not create false mismatches. Require the receipt engine to equal `slot.lane.name`.

Scan only:

`<lane root>/runs/*.json`

Never modify candidate receipts.

- [ ] **Step 4: Run Task 2 tests**

Run:

`pytest tests/test_automation_durability_watchdog.py -k "receipt" -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/automation_durability_watchdog.py tests/test_automation_durability_watchdog.py
git commit -m "feat: validate natural automation receipts"
```

---

### Task 3: Reconciliation planner, immutable artifacts, and CLI

**Files:**
- Modify: `tools/automation_durability_watchdog.py`
- Modify: `tests/test_automation_durability_watchdog.py`

**Interfaces:**
- Consumes: Task 1 and Task 2 interfaces
- Produces:
  - `Artifact(path: Path, payload: dict[str, object])`
  - `plan_reconciliation(root: Path, config: WatchdogConfig, now_utc: datetime, grace_minutes: int = 12, horizon_hours: int = 48) -> list[Artifact]`
  - `write_artifacts(root: Path, artifacts: list[Artifact]) -> list[Path]`
  - `main(argv: Sequence[str] | None = None) -> int`

- [ ] **Step 1: Write failing incident/backlog tests**

Add:
- before grace: no incident/backlog;
- after grace with no valid receipt: exactly one missing incident plus one backlog item;
- repeat planning with existing files: no overwrite and no duplicate artifacts;
- incident contains `kind=CHATGPT_NATURAL_RECEIPT_MISSING`, `natural_receipt_found=false`, `fallback_origin=GITHUB_WATCHDOG`, `scheduler_evidence_status=UNKNOWN`, `execution_authorized=false`, and receipt-candidate evidence;
- backlog contains `status=RECOVERY_PENDING_AI` and references the incident;
- neither artifact contains `run_origin=NATURAL_SCHEDULE`.

Paths:
- `reconciliation/missed/<lane>/<SLOT_ID>.json`
- `reconciliation/backlog/<lane>/<SLOT_ID>.json`.

- [ ] **Step 2: Write failing late-arrival tests**

Add:
- an existing incident plus later valid receipt creates exactly:
  `reconciliation/late_arrival/<lane>/<SLOT_ID>.json`;
- classification is `LATE_NATURAL_RECEIPT_AFTER_INCIDENT`;
- original incident remains byte-for-byte unchanged;
- no second backlog file is created.

- [ ] **Step 3: Write failing rolling-horizon and path-safety tests**

Add:
- a 48-hour run creates artifacts for all eligible missing slots after the portfolio start boundary;
- pre-binding slots are absent;
- `write_artifacts` rejects absolute paths, `..` traversal, `runs/`, `work/`, and any path outside `automation_intelligence/omega_stack_native_v2/reconciliation/`;
- deterministic JSON serialization is stable across two equivalent payloads.

Run:

`pytest tests/test_automation_durability_watchdog.py -k "incident or backlog or late or path or horizon" -v`

Expected: FAIL.

- [ ] **Step 4: Implement reconciliation planning**

Use incident existence + natural receipt state to choose:
- no action before grace;
- incident + backlog for newly missing slot;
- no action for already recorded still-missing slot;
- late-arrival artifact for an incident whose valid natural receipt now exists.

Never delete or mutate existing reconciliation artifacts.

- [ ] **Step 5: Implement safe writes and CLI**

CLI arguments:
- `--root PATH` required;
- `--now-utc ISO8601` optional for deterministic tests/manual probes;
- `--grace-minutes` default `12`;
- `--horizon-hours` default `48`.

Behavior:
- load target-branch control plane from `--root`;
- plan;
- write only new immutable reconciliation artifacts;
- print one JSON summary to stdout containing counts by artifact class and written paths;
- return 0 on success;
- return nonzero on malformed/inconsistent control plane or unsafe write attempt.

- [ ] **Step 6: Run focused and full watchdog tests**

Run:

`pytest tests/test_automation_durability_watchdog.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/automation_durability_watchdog.py tests/test_automation_durability_watchdog.py
git commit -m "feat: add immutable automation reconciliation"
```

---

### Task 4: GitHub Actions watchdog deployment

**Files:**
- Create: `.github/workflows/automation-durability-watchdog.yml`
- Modify: `tests/test_automation_durability_watchdog.py`

**Interfaces:**
- Consumes: `tools/automation_durability_watchdog.py --root <target checkout>`
- Produces: scheduled GitHub reconciliation commits on `automation/omega-native-v2`

- [ ] **Step 1: Write failing workflow-contract test**

Add a textual contract test that reads the workflow and asserts:
- triggers include `schedule: cron: "*/5 * * * *"` and `workflow_dispatch`;
- top-level `permissions` grants only `contents: write`;
- a `concurrency` group exists with `cancel-in-progress: false`;
- main/default source is checked out into one path for the watchdog script;
- `automation/omega-native-v2` is checked out into a separate target path;
- Python 3.11 is configured;
- watchdog command uses `--grace-minutes 12 --horizon-hours 48`;
- git stages only `automation_intelligence/omega_stack_native_v2/reconciliation`;
- workflow contains no `--force`, `force-with-lease`, `runs/` write command, or alternate token secret.

Run:

`pytest tests/test_automation_durability_watchdog.py -k "workflow_contract" -v`

Expected: FAIL because the workflow does not exist.

- [ ] **Step 2: Implement the workflow**

Use two `actions/checkout@v4` steps:
1. `ref: main`, `path: control` for the reviewed workflow/module source;
2. `ref: automation/omega-native-v2`, `path: state`, `fetch-depth: 0` for authoritative state and reconciliation writes.

Then:
- run `python control/tools/automation_durability_watchdog.py --root state --grace-minutes 12 --horizon-hours 48`;
- `git -C state add automation_intelligence/omega_stack_native_v2/reconciliation`;
- validate every staged path starts with that prefix;
- if no staged change, exit success without commit;
- configure GitHub Actions bot identity;
- commit with `automation: watchdog reconciliation <UTC> [skip ci]`;
- push `HEAD:automation/omega-native-v2` without force.

A push rejection due to concurrent branch advancement must fail the workflow visibly; the next scheduled invocation will recompute from current branch state.

- [ ] **Step 3: Run workflow-contract and complete watchdog suite**

Run:

`pytest tests/test_automation_durability_watchdog.py -v`

Expected: PASS.

Run:

`pytest tests tests_engine -q`

Expected: complete suite passes with zero failures. Record any pre-existing failure exactly; do not weaken tests.

- [ ] **Step 4: Commit feature branch**

```bash
git add .github/workflows/automation-durability-watchdog.yml tools/automation_durability_watchdog.py tests/test_automation_durability_watchdog.py
git commit -m "feat: add automation durability watchdog"
```

- [ ] **Step 5: Independent branch verification**

Before main integration:
- inspect diff to confirm no trading/engine files changed;
- verify no path outside the three implementation files plus approved docs was added;
- verify no secret/token name beyond default `GITHUB_TOKEN` behavior;
- verify no `NATURAL_SCHEDULE` value can be produced by watchdog artifacts.

- [ ] **Step 6: Integrate to `main` and observe a real workflow run**

The workflow must reach `main` because scheduled workflows are default-branch driven.

After integration:
- inspect the first actual `automation-durability-watchdog` Actions run;
- if it fails, inspect the exact job/step logs before any fix;
- if it succeeds with changes, inspect the reconciliation commit on `automation/omega-native-v2`;
- if it succeeds with no changes, use `workflow_dispatch` with the live state and verify the no-change path.

Do not claim deployment healthy from YAML inspection alone.

---

### Task 5: Promote the target-branch control plane to dual-plane r11 and sync knowledge

**Files:**
- Modify on `automation/omega-native-v2`: `automation_intelligence/omega_stack_native_v2/control_plane.json`
- Modify on `automation/omega-native-v2`: `automation_intelligence/omega_stack_native_v2/persistence_contract.json`
- Modify on `main`: `automation_intelligence/README.md`

**Interfaces:**
- Consumes: a verified real watchdog run from Task 4
- Produces: explicit r11 dual-plane policy and repository documentation

- [ ] **Step 1: Update target-branch control plane**

Set a new revision, e.g. `2026-09-29-native-v2-r11`, and add:
- `dual_plane_durability.enabled=true`;
- workflow path `.github/workflows/automation-durability-watchdog.yml`;
- watchdog schema version;
- `grace_minutes=12`;
- `horizon_hours=48`;
- reconciliation root;
- origin taxonomy `NATURAL_SCHEDULE | GITHUB_WATCHDOG | BACKFILL_RECOVERY`;
- rule: watchdog writes only reconciliation;
- rule: only natural ChatGPT runs may write `runs/`;
- observed workflow run ID/URL or commit evidence from Task 4.

Do not overwrite historical r10 evidence; update the current control-plane document truthfully.

- [ ] **Step 2: Update persistence contract**

Add dual-plane sections covering:
- missing-run incident schema;
- backlog schema and `RECOVERY_PENDING_AI`;
- late-arrival schema;
- immutable/no-overwrite rules;
- no-fabrication origin restrictions;
- GitHub watchdog failure semantics.

Keep v4.3 natural-run receipt semantics unchanged unless a new explicit protocol version is intentionally introduced. Prefer adding a watchdog/reconciliation schema version rather than renaming the natural-run protocol.

- [ ] **Step 3: Update `automation_intelligence/README.md`**

Document:
- authoritative stack state lives on `automation/omega-native-v2`;
- `main` may contain stale historical mirrors and is not scheduler truth;
- the dual-plane watchdog is deterministic durability infrastructure, not an AI worker;
- natural, watchdog, and backfill origins are separate;
- reconciliation namespace and recovery semantics.

Do not repair the root `README.md` conflict in this task.

- [ ] **Step 4: Verify the policy documents**

Re-fetch all three modified documents and verify:
- the five authoritative IDs are unchanged;
- `execution_authorized=false`;
- cadence/minutes unchanged;
- reconciliation root and workflow path exact;
- no stale ID is introduced.

- [ ] **Step 5: Commit**

Use narrowly scoped commits on the appropriate branches; do not mix target-branch state files and `main` documentation into an ambiguous single-branch claim.

---

### Task 6: Enable bounded AI backlog recovery without risking natural liveness

**Files:**
- Update the five existing ChatGPT automation prompts only after Task 4 and Task 5 verification.
- No scheduler changes.

**Interfaces:**
- Consumes: immutable `reconciliation/backlog/<lane>/<SLOT_ID>.json`
- Produces: optional `reconciliation/recovered/<lane>/<SLOT_ID>/<RECOVERY_RUN_ID>.json` with `run_origin=BACKFILL_RECOVERY`

- [ ] **Step 1: Preserve first-action liveness and permanence rules**

For each lane, retain:
- GitHub natural liveness `create_file` as absolute first action;
- same automation ID;
- same schedule;
- same protected-infrastructure/no-self-disable rule;
- `execution_authorized=false`.

- [ ] **Step 2: Add post-liveness backlog behavior**

After natural liveness succeeds:
1. make one bounded GitHub read of that lane's backlog directory;
2. if no unresolved backlog exists, continue the existing lane-specific optional work behavior;
3. if unresolved backlog exists, choose the oldest slot;
4. reconstruct only from actually available historical evidence;
5. create at most one immutable recovered artifact;
6. use `run_origin=BACKFILL_RECOVERY`;
7. state unobservable point-in-time fields as data gaps;
8. never create or alter a natural `runs/` receipt for the missed slot.

If runtime expires after the backlog read, leave the immutable backlog unresolved; no information is lost.

- [ ] **Step 3: Verify scheduler topology immediately after prompt updates**

Use the live automation registry and confirm:
- exactly the five authoritative tasks are enabled;
- minute offsets remain 00/12/24/36/48;
- IDs unchanged;
- retired tasks remain disabled.

- [ ] **Step 4: Observe natural post-update executions**

For each lane, distinguish:
- scheduler trigger;
- natural v4.3 receipt;
- optional work receipt;
- optional recovered-backlog artifact.

Do not infer one from another.

---

### Task 7: End-to-end acceptance and failure-mode proof

**Files:**
- No new production file expected.
- Test fixtures may be extended only in `tests/test_automation_durability_watchdog.py`.

**Interfaces:**
- Consumes: completed Tasks 1-6
- Produces: verified acceptance evidence for the dual-plane system

- [ ] **Step 1: Verify repository tests fresh**

Run:

`pytest tests/test_automation_durability_watchdog.py -v`

Expected: PASS, including all 15 spec-required behavior classes plus the Review Focus additions.

Run:

`pytest tests tests_engine -q`

Expected: zero failures. If repository-preexisting failures exist, report them and do not call the whole repository green.

- [ ] **Step 2: Verify real GitHub Actions health**

Inspect the latest watchdog workflow run:
- conclusion `success`;
- correct source workflow on `main`;
- target checkout `automation/omega-native-v2`;
- no unauthorized job permissions;
- no force push.

- [ ] **Step 3: Verify historical reconciliation**

Because the rolling window begins no earlier than authoritative identity binding:
- confirm at least one known missing post-binding slot is represented by an immutable incident and backlog item;
- confirm the real AION natural receipt slot is not falsely marked missing;
- confirm repeated watchdog execution does not alter existing incident bytes.

- [ ] **Step 4: Verify late-arrival behavior with a controlled fixture or safe test branch**

Demonstrate:
- missing incident exists;
- valid matching natural receipt later appears;
- late-arrival artifact is appended;
- incident remains unchanged.

Do not fabricate a natural receipt on the authoritative branch merely to test this path; use the unit fixture or an isolated test branch.

- [ ] **Step 5: Verify one real backlog recovery when a natural ChatGPT run succeeds**

After a lane produces a fresh natural receipt:
- observe at most one oldest backlog item consumed;
- verify recovered artifact origin is `BACKFILL_RECOVERY`;
- verify it references the original incident/backlog;
- verify natural historical truth remains unchanged.

If no lane successfully reaches post-liveness connector work yet, report this acceptance item as pending rather than fabricating it; the GitHub watchdog remains useful independently.

- [ ] **Step 6: Verify final live scheduler state**

Confirm:
- OMEGA enabled :00;
- Macro enabled :12;
- Flow enabled :24;
- AION enabled :36;
- DAEDALUS enabled :48;
- all retired tasks remain disabled;
- no completion state or watchdog action can self-disable them.

- [ ] **Step 7: Final review and completion claim**

Use `superpowers:verification-before-completion`. Report separately:
- ChatGPT scheduler health;
- natural receipt health;
- GitHub watchdog health;
- backlog/late-arrival health;
- recovery completion rate;
- any remaining external/platform limitation.

Do not collapse these into a single green/red status when evidence differs.
