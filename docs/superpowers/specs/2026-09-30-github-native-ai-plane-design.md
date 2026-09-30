# GitHub-Native AI Execution Plane Design

Date: 2026-09-30  
Status: Proposed for implementation after user review  
Repository: reppiks490/Icarus-engine  
Target system: OMEGA / Macro / Flow / AION / DAEDALUS automation stack

## 1. Problem statement

The current five-lane ChatGPT automation stack reliably triggers on schedule and remains enabled, but unattended ChatGPT-to-GitHub connector mutations are intermittent. The failure survives changes to prompt size, GitHub permission mode, create_file versus fetch_file+update_file, default branch versus state branch, and scheduled-call count. GitHub Actions watchdog execution and repository-native commits are independently healthy.

This means the remaining failure boundary is the unattended ChatGPT scheduled execution -> connected GitHub action hop. Continuing to modify the prompt-level persistence protocol is not justified by evidence.

## 2. Goal

Replace the unreliable persistence-critical hop with a GitHub-native execution plane that:

1. preserves the existing five logical lanes and cadence;
2. invokes the OpenAI Responses API directly from GitHub Actions;
3. writes immutable execution artifacts using repository-native Git operations;
4. preserves strict provenance between ChatGPT natural runs, GitHub-native AI runs, watchdog reconciliation, and recovery;
5. fails closed when credentials, API calls, model output validation, or repository writes fail;
6. does not authorize live trading or execution;
7. supports safe staged cutover and rollback;
8. retains the existing ChatGPT scheduler as non-authoritative canary evidence until the new plane proves stable.

## 3. Non-goals

This design does not:
- authorize trading, deployment, publication, or order execution;
- claim that successful model execution proves strategy profitability or predictive validity;
- fabricate ChatGPT natural receipts for GitHub-native executions;
- remove the watchdog or reconciliation history;
- reactivate retired legacy automations;
- require the user to paste API credentials into chat;
- migrate unrelated ICARUS/AEGIS workflows.

## 4. Architecture

### 4.1 Control planes

The system becomes three explicit planes:

1. **GitHub-native AI execution plane — authoritative**
   - GitHub Actions schedules the five lanes.
   - Each lane calls the OpenAI Responses API directly.
   - Each lane validates the model response.
   - Each lane writes immutable run artifacts and a machine-readable execution receipt using Git.
   - Origin: `GITHUB_NATIVE_AI`.

2. **ChatGPT scheduler plane — compatibility/canary only during cutover**
   - Existing five ChatGPT automations remain enabled initially.
   - Their triggers are observed as scheduler-health evidence.
   - Their GitHub writes are no longer required for authoritative persistence after cutover begins.
   - Origin remains `NATURAL_SCHEDULE` only if an actual natural ChatGPT receipt is successfully written.
   - They must never impersonate `GITHUB_NATIVE_AI`.

3. **GitHub watchdog / reconciliation plane**
   - Existing watchdog remains independent.
   - It tracks expected authoritative GitHub-native slots after cutover.
   - It writes only under `reconciliation/`.
   - Origin: `GITHUB_WATCHDOG`.
   - It never fabricates AI outputs or natural receipts.

### 4.2 Five lane cadence

America/Chicago:
- OMEGA: :00
- Macro: :12
- Flow: :24
- AION: :36
- DAEDALUS: :48

GitHub cron is UTC-based and DST-insensitive at configuration time. Therefore the workflow must not encode Chicago local wall-clock offsets directly. Instead:

- one frequent dispatcher workflow runs every 4-5 minutes;
- it computes current America/Chicago local time with `zoneinfo`;
- it resolves whether one lane's nominal slot is due within a narrow dispatch window;
- it creates a deterministic slot ID from the corresponding UTC instant;
- it suppresses duplicate dispatches by checking immutable run/failure artifacts for that slot.

This preserves the Chicago schedule across DST transitions and avoids maintaining separate summer/winter cron definitions.

## 5. OpenAI API integration

### 5.1 API surface

Use the OpenAI Responses API from a small Python runner. Model configuration is repository-controlled and versioned.

Initial default:
- model: configurable through repository variable, with a conservative default appropriate to reasoning/coding work;
- reasoning effort: lane-specific configuration;
- output: strict JSON contract;
- network timeout: bounded;
- retry policy: bounded, exponential backoff, no unbounded retry.

### 5.2 Credentials

The runner reads `OPENAI_API_KEY` from GitHub Actions secrets.

Rules:
- never commit credentials;
- never echo credentials to logs;
- never include credentials in model input, artifacts, stack traces, or failure JSON;
- if the secret is absent, emit a fail-closed execution-failure artifact and stop;
- no alternate token fallback;
- no credential synthesis;
- no requirement for the user to paste the key into chat.

If organization/project scoping variables are needed later, add them as GitHub secrets/variables with the same non-logging rules.

## 6. Repository layout

Under:
`automation_intelligence/omega_stack_native_v3/`

Proposed structure:

- `control_plane.json`
- `execution_contract.json`
- `lanes/<lane>/prompts/system.md`
- `lanes/<lane>/prompts/task.md`
- `lanes/<lane>/runs/<SLOT_ID>/<RUN_ID>.json`
- `lanes/<lane>/outputs/<SLOT_ID>/<RUN_ID>.json`
- `lanes/<lane>/failures/<SLOT_ID>/<RUN_ID>.json`
- `reconciliation/missed/<lane>/<SLOT_ID>.json`
- `reconciliation/late/<lane>/<SLOT_ID>.json`
- `reconciliation/backlog/<lane>/<SLOT_ID>.json`
- `cutover/acceptance.json`

The v2 namespace remains immutable historical evidence during migration.

## 7. Provenance model

Allowed origins:

- `NATURAL_SCHEDULE`
- `GITHUB_NATIVE_AI`
- `GITHUB_WATCHDOG`
- `BACKFILL_RECOVERY`

A GitHub-native run must include at minimum:

- schema_version
- engine
- lane
- RUN_ID
- SLOT_ID
- slot_local
- slot_utc
- started_at_utc
- completed_at_utc
- run_origin = GITHUB_NATIVE_AI
- workflow_run_id
- workflow_run_attempt
- workflow_sha
- repository
- branch
- model
- reasoning_effort
- request_fingerprint
- response_id when available
- response_status
- output_validation_status
- RUN_STATUS
- FINALIZATION_STATUS
- DATA_GAPS
- CONFLICTS
- execution_authorized = false

No GitHub-native artifact may use `run_origin=NATURAL_SCHEDULE`.

## 8. Lane execution contract

Each lane run follows this sequence:

1. Resolve authoritative slot.
2. Check for an existing terminal artifact for that slot.
3. Load versioned lane prompt/config from the checked-out commit.
4. Build a bounded model request.
5. Call Responses API.
6. Validate the returned JSON against the lane schema.
7. Write output artifact to a temporary path.
8. Write execution receipt to a temporary path.
9. Atomically move both into the immutable slot directory.
10. Commit only lane-scoped artifacts.
11. Push with normal GitHub Actions credentials.
12. If any step fails, write a failure artifact where safely possible and return non-zero.

The model is never allowed to push directly to GitHub. GitHub Actions owns persistence.

## 9. Failure semantics

### 9.1 Missing API key
- status: `CONFIGURATION_BLOCKED`
- workflow fails visibly
- no success receipt
- no model call

### 9.2 API transport / rate-limit failure
- bounded retry
- terminal status: `MODEL_TRANSPORT_FAILED`
- failure artifact includes sanitized HTTP/status metadata only
- workflow fails visibly

### 9.3 Invalid model output
- no repair-by-invention
- one optional structured reformat attempt may be allowed only if the underlying semantic content is retained and the contract explicitly permits it
- otherwise status: `OUTPUT_VALIDATION_FAILED`

### 9.4 Git conflict / concurrent slot execution
- refetch branch
- if the exact slot already has a terminal artifact, classify duplicate and exit safely
- otherwise fail closed
- never force push

### 9.5 Watchdog observation
The watchdog does not infer scheduler success from GitHub Actions existence alone. It validates the authoritative run receipt fields for the exact slot.

## 10. Security and authority

- `execution_authorized=false` is immutable in runner code and validated before commit.
- No workflow may place trades, submit orders, alter brokerage state, or set an execution-authorization flag.
- Model outputs are advisory/research artifacts.
- Repository write scope is constrained to the v3 automation namespace plus explicitly approved docs/tests.
- Workflow permissions use least privilege: normally `contents: write`; no administration privileges.
- Secrets are not accessible to pull requests from forks.
- Failure logs redact environment values.

## 11. Dispatcher design

Create:
- `tools/github_native_ai_dispatcher.py`
- `tools/github_native_ai_runner.py`
- `.github/workflows/github-native-ai-plane.yml`

Dispatcher responsibilities:
- load v3 control plane;
- compute America/Chicago local time;
- identify due lane;
- derive canonical UTC slot ID;
- skip if outside dispatch tolerance;
- skip if terminal slot artifact already exists;
- invoke exactly one lane runner;
- expose deterministic diagnostic output.

Recommended dispatch tolerance: approximately +/-4 minutes around the nominal lane boundary. Exact tolerance must be tested against GitHub scheduled-event delay behavior and encoded in the contract.

## 12. Testing strategy

### 12.1 Unit tests
- DST spring-forward and fall-back slot generation
- exact lane mapping
- duplicate suppression
- slot tolerance boundaries
- no pre-binding slot generation
- missing-secret failure
- request fingerprint determinism
- JSON schema validation
- response-id capture
- output rejection
- rate-limit retry bound
- secret redaction
- lane path isolation
- execution_authorized invariant
- provenance-origin invariant

### 12.2 Integration tests
- mock Responses API success
- mock 401/403
- mock 429 then success
- mock timeout
- malformed model JSON
- Git conflict / duplicate slot
- watchdog acceptance of valid GitHub-native receipt
- watchdog rejection of invalid origin or slot

### 12.3 Repository CI
Run on Python 3.11+ and preserve current multi-version test coverage where practical.

## 13. Cutover plan

### Stage A — build dark
- v3 code/workflow lands disabled for scheduled execution.
- workflow_dispatch only.
- no authoritative topology change.

### Stage B — manual proof
For one lane:
- manually dispatch a known test slot in non-production namespace;
- verify API call, validation, artifact commit, failure behavior, and watchdog parsing.

### Stage C — single-lane scheduled canary
- enable AION or the most observable lane first;
- keep v2 ChatGPT lane enabled;
- v3 lane is authoritative only for its own test namespace initially.

### Stage D — five-lane shadow
- enable all five v3 schedules;
- continue existing ChatGPT tasks as canaries.
- require two consecutive valid v3 runs per lane.

### Stage E — authoritative cutover
Acceptance:
- 5/5 lanes each have >=2 consecutive valid `GITHUB_NATIVE_AI` receipts;
- no duplicate slot commits;
- watchdog validates all recent slots;
- CI green;
- no secret leakage;
- execution_authorized remains false.

Then:
- set v3 as authoritative execution source;
- demote v2 natural persistence to historical/canary status;
- keep ChatGPT tasks enabled only if they still provide useful independent scheduler evidence;
- do not delete v2 history.

## 14. Rollback

Rollback trigger examples:
- repeated API failures;
- credential/configuration errors;
- duplicate slot corruption;
- watchdog incompatibility;
- secret leakage;
- repository write-scope violation.

Rollback action:
- disable v3 scheduled workflow;
- leave v3 artifacts immutable;
- restore v2 as observation-only containment;
- do not reactivate retired legacy loops;
- investigate with preserved failure evidence.

## 15. Acceptance criteria

The architectural repair is complete only when:

1. all five GitHub-native lanes schedule correctly in America/Chicago semantics;
2. each lane produces two consecutive valid immutable receipts;
3. model outputs validate against their lane schema;
4. watchdog correctly validates v3 slots and detects a deliberately simulated miss in tests;
5. repository CI is green;
6. no secret appears in logs or committed artifacts;
7. no workflow writes outside approved namespace;
8. duplicate executions are idempotently suppressed;
9. `execution_authorized=false` is enforced in code and tests;
10. ChatGPT connector persistence is no longer required for authoritative system durability.

## 16. Open implementation dependency

The only expected external setup dependency is an OpenAI API credential available to GitHub Actions as `OPENAI_API_KEY`. The connected GitHub app cannot inspect Actions secret names, so implementation must detect absence fail-closed. If the secret is not already configured, the repository owner must add it through GitHub's Actions secret UI; the key must never be sent through chat.

## 17. Decision

Proceed with GitHub-native execution as the replacement persistence/execution architecture. Do not perform further prompt-level connector experiments unless new evidence invalidates this root-cause conclusion.
