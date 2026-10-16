# GitHub-Native Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GitHub Actions the authoritative credential plane for ICARUS while preserving legacy aliases and preventing secret exposure.

**Architecture:** A machine-readable credential contract defines canonical environment names and legacy aliases. A Python resolver consumes that contract with canonical-first precedence and redacted diagnostics. A GitHub Actions health workflow explicitly wires repository secrets and verifies presence without printing values; contract tests prevent drift.

**Tech Stack:** Python 3.11+, pytest, JSON, GitHub Actions YAML.

**Spec:** `docs/superpowers/specs/2026-10-15-github-native-credentials-design.md`

## Global Constraints

- Never print, persist, commit, upload, or artifact secret values.
- GitHub Actions is the runtime credential authority; chats are not credential stores.
- Canonical names are stable; legacy aliases are compatibility shims.
- Canonical value wins over aliases; aliases resolve in declared order.
- No dynamic secret enumeration such as `toJSON(secrets)`.

## Review Focus

- Empty-string secrets must be treated as unavailable, not valid credentials.
- Canonical and alias values simultaneously present must deterministically choose canonical.
- Unknown credential names must fail clearly without exposing environment contents.
- Workflow secret references must stay synchronized with the contract.
- Diagnostic output must never contain credential values.

---

### Task 1: Credential contract and resolver

**Files:**
- Create: `config/credential_contract.json`
- Create: `icarus_engine/security/credentials.py`
- Create: `icarus_engine/security/__init__.py`
- Test: `tests/test_github_native_credentials.py`

**Interfaces:**
- Produces: `load_contract(path: Path | None = None) -> dict[str, CredentialSpec]`
- Produces: `resolve_credential(name: str, env: Mapping[str, str] | None = None) -> str | None`
- Produces: `credential_status(name: str, env: Mapping[str, str] | None = None) -> CredentialStatus`

- [ ] **Step 1: Write failing resolver/contract tests** for canonical precedence, alias fallback, empty values, unknown names, and redacted status.
- [ ] **Step 2: Run** `pytest tests/test_github_native_credentials.py -v` and confirm failure because the new module/contract does not exist.
- [ ] **Step 3: Implement** the JSON contract and minimal resolver interfaces.
- [ ] **Step 4: Run** `pytest tests/test_github_native_credentials.py -v` and confirm PASS.
- [ ] **Step 5: Commit** contract/resolver/tests.

### Task 2: GitHub Actions health verifier

**Files:**
- Create: `tools/credential_health.py`
- Create: `.github/workflows/github-native-credential-health.yml`
- Modify: `tests/test_github_native_credentials.py`

**Interfaces:**
- Consumes: `load_contract`, `credential_status`
- Produces: CLI exit code 0 for report mode; strict mode non-zero only for explicitly required missing credentials.

- [ ] **Step 1: Add failing tests** proving workflow references only declared aliases/canonical names, contains no dynamic secret enumeration, and health output is redacted.
- [ ] **Step 2: Run** targeted tests and confirm the expected failures.
- [ ] **Step 3: Implement** the redacted health CLI and explicit workflow wiring.
- [ ] **Step 4: Run** targeted tests and confirm PASS.
- [ ] **Step 5: Commit** verifier/workflow/tests.

### Task 3: Agent handoff and anti-drift contract

**Files:**
- Create: `docs/agent-handoffs/GITHUB_NATIVE_CREDENTIALS.md`
- Create: `AGENT_CREDENTIALS.md`
- Modify: `tests/test_github_native_credentials.py`

**Interfaces:**
- Produces: durable instructions for all AI units to consume canonical names through GitHub Actions and never request plaintext values.

- [ ] **Step 1: Add failing tests** that require the handoff to reference the canonical contract, health workflow, and non-extraction rule.
- [ ] **Step 2: Run** targeted tests and confirm failure.
- [ ] **Step 3: Write** the handoff documents including the message that GitHub-native API data is available where the corresponding health check reports present, and agents should begin using it through the canonical interface.
- [ ] **Step 4: Run** targeted tests and confirm PASS.
- [ ] **Step 5: Commit** documentation/tests.

### Task 4: Integration verification

**Files:**
- Modify only if failures reveal contract drift in existing workflow references.

**Interfaces:**
- Consumes all prior tasks.

- [ ] **Step 1: Run** `pytest tests/test_github_native_credentials.py -v`.
- [ ] **Step 2: Run** the repository's full `pytest` suite and record any pre-existing failures separately.
- [ ] **Step 3: Open a PR** from `atlas/github-native-credentials` to `main` to trigger branch/PR Actions.
- [ ] **Step 4: Inspect Actions jobs/logs** and repair implementation-caused failures.
- [ ] **Step 5: Merge only after the new credential tests and relevant Actions are green; otherwise report the precise blocker rather than claiming completion.
