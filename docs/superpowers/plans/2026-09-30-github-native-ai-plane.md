# GitHub-Native AI Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unreliable unattended ChatGPT→GitHub connector persistence boundary with a GitHub Actions-native AI execution plane for OMEGA, Macro, Flow, AION, and DAEDALUS.

**Architecture:** A GitHub Actions dispatcher resolves America/Chicago lane slots, invokes a Python runner, calls the OpenAI Responses API with a repository-secret credential, validates structured JSON, and commits immutable v3 artifacts. Existing v2 ChatGPT tasks remain enabled as canaries during shadow rollout; provenance remains distinct and the watchdog is extended for v3.

**Tech Stack:** Python 3.11 standard library, GitHub Actions, OpenAI Responses API over HTTPS, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-github-native-ai-plane-design.md`

## Global Constraints
- Lane times: OMEGA :00, Macro :12, Flow :24, AION :36, DAEDALUS :48 in America/Chicago.
- `execution_authorized=false` is immutable.
- GitHub-native origin is `GITHUB_NATIVE_AI`; never impersonate `NATURAL_SCHEDULE`.
- Credentials are never committed or logged.
- No force push.
- Writes are limited to the v3 namespace plus approved docs/tests/workflows/tools.
- V2 history remains immutable.
- Missing credentials/API/output validation fail closed.
- Cutover requires two consecutive valid v3 receipts per lane.

## Review Focus
- DST spring/fall transitions.
- Delayed schedule delivery and duplicate suppression.
- Missing/invalid `OPENAI_API_KEY` without secret leakage.
- Malformed model output never becoming success.
- Concurrent slot attempts never corrupting or cross-writing lanes.

---

### Task 1: V3 control plane and deterministic slot dispatcher
**Files:** Create `automation_intelligence/omega_stack_native_v3/control_plane.json`, `execution_contract.json`, `tools/github_native_ai_dispatcher.py`, `tests/test_github_native_ai_dispatcher.py`.

**Interfaces:** `load_control_plane(root: Path) -> ControlPlane`; `resolve_due_slot(now_utc: datetime, control: ControlPlane, tolerance_minutes: int) -> Slot | None`; `terminal_artifact_exists(root: Path, slot: Slot) -> bool`.

- [ ] Write failing tests for five lane mappings, no-slot windows, ±4-minute boundary, DST spring/fall, deterministic UTC slot IDs, duplicate suppression, and immutable execution flag.
- [ ] Run `pytest tests/test_github_native_ai_dispatcher.py -q` and verify RED.
- [ ] Implement minimal standard-library control plane + dispatcher using `zoneinfo.ZoneInfo`.
- [ ] Run the same tests and verify GREEN.
- [ ] Commit `feat: add v3 deterministic lane dispatcher`.

### Task 2: Fail-closed OpenAI Responses client
**Files:** Create `tools/github_native_ai_openai.py`, `tests/test_github_native_ai_openai.py`.

**Interfaces:** `call_responses_api(request: ModelRequest, api_key: str, transport: Transport | None = None) -> ModelResponse`; `validate_lane_output(payload: object, lane: str) -> dict[str, object]`.

- [ ] Write failing tests for missing key, deterministic request payload, authorization-header secrecy, bounded 429 retry, timeout, 401/403, malformed JSON, missing output, lane schema, and redaction.
- [ ] Run `pytest tests/test_github_native_ai_openai.py -q` and verify RED.
- [ ] Implement stdlib `urllib.request` Responses client with bounded retry/timeout and default endpoint `https://api.openai.com/v1/responses`.
- [ ] Run tests and verify GREEN.
- [ ] Commit `feat: add fail-closed Responses API client`.

### Task 3: Lane runner and immutable artifacts
**Files:** Create `tools/github_native_ai_runner.py`, `tests/test_github_native_ai_runner.py`, shared system prompt and five lane task prompts under `automation_intelligence/omega_stack_native_v3/lanes/`.

**Interfaces:** `run_lane(root: Path, slot: Slot, env: Mapping[str,str]) -> RunResult`. Runner writes only `lanes/<lane>/{runs,outputs,failures}/<SLOT_ID>/...`.

- [ ] Write failing tests for success, missing-key failure, API failure, invalid output, request fingerprint, path isolation, duplicates, no overwrite, provenance, and immutable execution flag.
- [ ] Verify RED.
- [ ] Implement runner + versioned prompts; runner never calls GitHub APIs.
- [ ] Verify GREEN.
- [ ] Commit `feat: add GitHub-native lane runner`.

### Task 4: GitHub Actions workflow
**Files:** Create `.github/workflows/github-native-ai-plane.yml`, `tests/test_github_native_ai_workflow_contract.py`.

**Interfaces:** Scheduled/workflow_dispatch execution with `contents: write`; environment injects `OPENAI_API_KEY` from repository secrets.

- [ ] Write failing workflow tests requiring frequent staggered schedule, workflow_dispatch, Python 3.11, contents write, concurrency/no cancel, no force push, env-only secret use, v3 staging guard, and no v2 natural writes.
- [ ] Verify RED.
- [ ] Implement workflow: checkout main, dispatcher/runner, stage only v3, commit only if changed, safe one-time pull/rebase conflict handling, push without force.
- [ ] Verify GREEN.
- [ ] Commit `feat: add GitHub-native AI workflow`.

### Task 5: Extend watchdog for v3
**Files:** Modify `tools/automation_durability_watchdog.py`, `tests/test_automation_durability_watchdog.py`.

- [ ] Write failing tests for valid v3 receipt, invalid origin, wrong slot/lane, unauthorized execution, malformed output, and deliberate miss.
- [ ] Verify RED.
- [ ] Implement explicit dual-version validation preserving v2 behavior.
- [ ] Verify GREEN.
- [ ] Commit `feat: validate v3 GitHub-native receipts`.

### Task 6: Cutover, CI, and activation
**Files:** Create `automation_intelligence/omega_stack_native_v3/cutover/acceptance.json`; modify v3 control plane only as evidence changes.

- [ ] Run `pytest -q`; require zero failures.
- [ ] Open PR and require all repository CI jobs green.
- [ ] Merge to main only after CI green.
- [ ] Dispatch diagnostic/manual mode if supported and verify slot resolution, namespace guard, and credential-presence classification without secret exposure.
- [ ] If `OPENAI_API_KEY` exists, execute one controlled AION canary and verify API success + immutable artifacts + watchdog acceptance.
- [ ] If key is absent, leave workflow deployed fail-closed and record `CONFIGURATION_BLOCKED_OPENAI_API_KEY_MISSING`; do not fake completion.
- [ ] Enable scheduled shadow mode after canary succeeds; keep five ChatGPT tasks enabled as canaries.
- [ ] Require two consecutive valid v3 receipts per lane before authoritative cutover.
- [ ] Final `pytest -q`, inspect workflow/artifacts, verify no out-of-namespace writes and execution flag false.
- [ ] Commit `automation: record v3 cutover state`.
