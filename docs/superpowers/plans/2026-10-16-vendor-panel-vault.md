# Vendor Panel Vault Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the 13 plaintext vendor panel CSVs from the public working tree only after current-main code proves every file is authenticated, encrypted, labelled, and restorable from the vault.

**Architecture:** Extend the existing AES-256-GCM content-addressed depth vault rather than creating a second storage system. The panel is a `preserved_original` cache with explicit provenance; a fail-closed loader restores missing panel files only from authenticated vault objects. GitHub Actions performs seal → label → verify → private restore drill before any deletion commit is allowed.

**Tech Stack:** Python 3.11+, stdlib, `cryptography`, pytest, GitHub Actions, existing ICARUS depth vault.

**Spec:** `reppiks490/icarus-owner-actions/coordination/events/2026/10/16/chatgpt-20261016-atlas-coordination-futures/20261016T031000Z-l1-j02-reclaim-handoff.json` plus superseded `reppiks490/Icarus-engine#135` as source material only.

## Global Constraints

- Do not expose `ICARUS_DATA_ARCHIVE_KEY`, Databento credentials, or plaintext licensed payloads in logs/artifacts.
- Do not rewrite Git history in this workstream; removing files from the current tree does not erase prior public history.
- Do not remove any `data/panel/*_5m.csv` until a current-branch Actions run proves encrypted inventory, authentication, provenance labels, and a private restore drill.
- Preserve existing corpus/sweep vault behavior and current ingestion protections.
- Live broker arming and execution authority remain disabled.

## Review Focus

- Malicious manifest relative paths or symlink escapes must never write outside the requested restore root.
- A malformed object hash must never be interpreted as a filesystem path.
- Missing/ambiguous provenance must be reported, never guessed.
- Partial/corrupt panel restores must fail closed rather than silently shrinking the research universe.
- Verification must decrypt in memory and must not write plaintext during its authentication pass.

---

### Task 1: Preregister the security contract

**Files:**
- Create: `tests/test_vendor_panel_vault.py`

**Interfaces:**
- Consumes: current `tools.depth_vault.seal/restore`, `tools.asset_panel.load_panel`.
- Produces: failing contract tests for explicit `.csv` sealing, safe restore paths, provenance labels, in-memory verify, receipt behavior, and panel recovery.

- [ ] **Step 1:** Add synthetic-only tests for explicit CSV sealing/restoring, traversal/symlink/hash rejection, preserved-original labels, tamper detection, missing-key recovery instructions, corrupt/partial panel rejection, and sentinel receipt visibility.
- [ ] **Step 2:** Run `python -m pytest -q tests/test_vendor_panel_vault.py -p no:cacheprovider -o addopts= --import-mode=importlib`.
- [ ] **Step 3:** Confirm RED failures are only missing L1/J02 behavior, not test harness errors.
- [ ] **Step 4:** Commit the RED tests.

### Task 2: Harden and extend the existing vault

**Files:**
- Modify: `tools/depth_vault.py`
- Test: `tests/test_vendor_panel_vault.py`

**Interfaces:**
- Produces: `seal(..., suffixes=...)`, safe restore path/object validation, `label(vault, ledger_dir)`, `verify(vault, env, ledger_dir)`, and `write_receipt(path, receipt, refresh_h)`.

- [ ] **Step 1:** Implement explicit suffix selection without changing the default corpus/sweep suffixes.
- [ ] **Step 2:** Reject absolute, parent-traversal, backslash, symlink-escape and malformed-hash manifest entries before reading/writing paths.
- [ ] **Step 3:** Build deterministic object provenance from `manifest.json`, hand-written `sources.json`, and exactly-one matching spend-ledger entry; preserved originals receive no invented purchase time.
- [ ] **Step 4:** Verify every manifest object by AES-GCM decrypt + decompress + SHA-256 + byte count entirely in memory and compare every label field against regenerated provenance.
- [ ] **Step 5:** Run focused tests GREEN, then the existing `tests/test_depth_vault.py` regression suite.
- [ ] **Step 6:** Commit.

### Task 3: Make panel use fail closed

**Files:**
- Modify: `tools/asset_panel.py`
- Test: `tests/test_vendor_panel_vault.py`

**Interfaces:**
- Produces: `ensure_panel(root=None, vault=None, env=None) -> Path`; `load_panel()` calls it before reading bars.

- [ ] **Step 1:** Restore only missing expected panel files from the vault inventory; require complete manifest coverage.
- [ ] **Step 2:** Hash-check every expected restored/present file against the manifest; error on corruption or incomplete inventory.
- [ ] **Step 3:** When recovery needs a key and none is usable, raise an actionable error instead of returning an empty panel.
- [ ] **Step 4:** Run focused tests GREEN.
- [ ] **Step 5:** Commit.

### Task 4: Add provenance and verification observability

**Files:**
- Create: `data/depth_vault/sources.json`
- Modify: `tools/data_sentinel.py`
- Test: `tests/test_vendor_panel_vault.py`

**Interfaces:**
- `sources.json` declares `corpus`, `sweep`, and `panel` origins/providers with no secrets.
- Sentinel reads `automation_intelligence/sentinel/vault_verify.json` and reports verdict/time/failure count.

- [ ] **Step 1:** Port only factual provenance from #135, retaining the explicit note that panel rights/exposure are unverified and tree deletion does not erase history.
- [ ] **Step 2:** Add sentinel receipt reporting without making `NOT_RUN` look healthy.
- [ ] **Step 3:** Run focused and sentinel tests.
- [ ] **Step 4:** Commit.

### Task 5: Prove encrypted recovery on the branch

**Files:**
- Modify: `.github/workflows/depth-vault.yml`
- Generated by Actions after success: `data/depth_vault/manifest.json`, `data/depth_vault/objects/*.bin`, `data/depth_vault/origins.json`, `automation_intelligence/sentinel/vault_verify.json`

**Interfaces:**
- Workflow sequence: existing tests → restore caches → seal corpus/sweep → seal `panel` with `.csv` → label → verify → private temp restore drill → existing D1 → commit only ciphertext/metadata/receipt.

- [ ] **Step 1:** Add branch-safe workflow triggering for `atlas/**` and include the new security test.
- [ ] **Step 2:** Add panel sealing, label, verify, and a temporary-directory restore drill; never upload restored plaintext as an artifact.
- [ ] **Step 3:** Push and require a successful exact-head Actions run using existing repository secrets without printing them.
- [ ] **Step 4:** Read back the branch manifest/origins/receipt and require exactly 13 panel CSV inventory entries, 13 authenticated panel objects, zero label mismatches/failures, and restore-drill success.
- [ ] **Step 5:** Commit/accept the workflow-generated ciphertext state only after those checks pass.

### Task 6: Remove plaintext from the current tree only after proof

**Files:**
- Delete only after Task 5 evidence: `data/panel/{EEM,GLD,IEF,IWM,NVDA,QQQ,SLV,SPY,TLT,USO,UUP,VXX,XLE}_5m.csv`
- Preserve: `data/panel/_verified_tickers.json` unless a current consumer proves it should move too.

**Interfaces:**
- `tools.asset_panel.ensure_panel()` is now the recovery path.

- [ ] **Step 1:** Re-check Task 5 evidence immediately before deletion.
- [ ] **Step 2:** Delete the 13 CSVs on the feature branch; do not rewrite repository history.
- [ ] **Step 3:** Run focused tests plus the combined repo suite on the exact deletion head.
- [ ] **Step 4:** Run the branch depth-vault workflow again with the CSVs absent; require label/verify and private restore drill to succeed from ciphertext alone.
- [ ] **Step 5:** Merge only after exact-head tests and recovery evidence are GREEN.
