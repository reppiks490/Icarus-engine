# Full-System Agent Intelligence Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every ICARUS AI unit consume one revision-bound, research-safe full-system context and expose any missing/stale subsystem as an explicit gap.

**Architecture:** Add a machine-readable intelligence contract plus deterministic context generator over the complete tracked Engine tree and selected external repo state. Feed the resulting context ID into native-five research, federation, sentinel, and interactive-agent instructions while preserving centralized provider collection and zero execution authority.

**Tech Stack:** Python 3.11+, Git/GitHub Actions, JSON contracts, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-full-system-agent-intelligence-contract.md`

## Global Constraints

- GitHub remains credential authority; no plaintext secrets.
- No duplicate paid/rate-limited provider pulls for per-agent copies.
- No raw licensed vendor payloads in git.
- Execution/production/promotion authority stays false.
- Missing required context fails closed; conditional gaps stay explicit.

## Review Focus

- Secret-like values in source documents must not leak into the manifest.
- Context freshness must not silently use malformed/naive clocks.
- External repo checkout failure must remain explicit, not guessed.
- Automated lanes must bind receipts to exactly one context ID.
- Federation must witness the exact context artifact at the packet source revision.

---

### Task 1: Contract and generator

**Files:**
- Create: `config/agent_intelligence_contract.json`
- Create: `tools/agent_intelligence_context.py`
- Test: `tests/test_agent_intelligence_context.py`

**Interfaces:**
- Produces: `build_context(root: Path, *, external_repos: Mapping[str, Path], source_commit: str, observed_at: str) -> dict`
- Produces: `automation_intelligence/agent_context/full_system_context.json`

- [ ] Write failing tests for complete git inventory, required/conditional gaps, no-secret output, authority flags, deterministic `context_id`, and external revision binding.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement the contract and generator.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 2: Interactive-agent entrypoints and notices

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `AGENT_CREDENTIALS.md`
- Create: `AGENT_FULL_CONTEXT.md`
- Create immutable notices under `coordination/inbox/to-claude/` and `coordination/inbox/to-atlas/`
- Modify: `coordination/board/chatgpt.md`

**Interfaces:**
- Consumes: full-system context manifest path and `context_id`.
- Produces: mandatory read/ack protocol for interactive units.

- [ ] Add tests that assert all native agent entrypoints require the full context manifest and forbid plaintext-key copying.
- [ ] Add the shared-context instructions and messages.
- [ ] Run tests.
- [ ] Commit.

### Task 3: Automated research consumption

**Files:**
- Modify: `tools/native_research.py`
- Modify: `.github/workflows/native-five-research.yml`
- Modify: `tests/test_native_research.py`

**Interfaces:**
- Consumes: `load_shared_context(root: Path) -> dict`.
- Produces: every lane receipt with `full_system_context_id` and `shared_context` metadata; Omega gets aggregate gap map.

- [ ] Add failing tests for lane receipt context binding and Omega gap visibility.
- [ ] Implement context loading/injection without changing lane measurement semantics.
- [ ] Run native-research tests.
- [ ] Commit.

### Task 4: Federation witness

**Files:**
- Modify: `icarus_engine/interrepo_bridge.py`
- Modify: `tools/export_peer_intelligence.py`
- Modify: `.github/workflows/interrepo-peer-intelligence.yml`
- Modify: `tests_engine/test_interrepo_bridge.py`

**Interfaces:**
- Consumes: full-system context manifest at packet source revision.
- Produces: revision-bound packet witness carrying `full_system_context_id` and blob SHA.

- [ ] Add failing packet/witness tests.
- [ ] Add context witness without expanding authority or changing existing historical source semantics.
- [ ] Run interrepo tests.
- [ ] Commit.

### Task 5: Workflow and sentinel gap gate

**Files:**
- Create: `.github/workflows/full-system-agent-context.yml`
- Modify: `tools/data_sentinel.py`
- Modify: `.github/workflows/data-sentinel.yml`
- Test: `tests/test_data_sentinel.py` and `tests/test_agent_intelligence_context.py`

**Interfaces:**
- Workflow checks out Engine, `reppiks490/Icarus`, and `reppiks490/icarus-owner-actions` read-only.
- Sentinel reports full-context gap counts/severity.

- [ ] Add failing workflow-contract/sentinel tests.
- [ ] Implement scheduled/push generation and safe persistence.
- [ ] Run tests.
- [ ] Commit.

### Task 6: Production verification and gap closure

**Files:**
- Generated: `automation_intelligence/agent_context/full_system_context.json`
- Generated/updated federation/native-research/sentinel receipts.

- [ ] Run the exact-head test matrix.
- [ ] Merge only after green checks.
- [ ] Verify live main workflow with real repository state and external checkouts.
- [ ] Inspect generated gap list; fix implementation-caused gaps and leave only genuine unavailable/invalid/entitlement gaps.
- [ ] Verify native-five receipts and peer packet carry the live context ID.
- [ ] Send final immutable status message to Claude and Atlas and update ChatGPT/Codex board.
