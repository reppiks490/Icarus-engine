# Full-System Agent Intelligence Contract

**Status:** owner-directed implementation, 2026-10-16.

## Intent

Every AI unit that works on ICARUS must have a common, revision-bound view of the entire accessible system and the same verified data/research surfaces. No worker may silently operate from a provider-only, repo-only, lane-only, or stale partial view and then claim system-wide awareness.

This applies to interactive workers (ChatGPT/Codex, Claude, Atlas and future coding/research agents), automated research lanes (Flow, Macro, Aion, Daedalus, Omega), and federation consumers in `reppiks490/Icarus`.

## Non-negotiable constraints

- GitHub is the runtime credential authority; no plaintext secrets enter prompts, logs, commits, receipts, or public artifacts.
- Provider collection is centralized. AI units consume shared verified outputs; they do not duplicate paid/rate-limited API pulls merely to obtain their own copy.
- Licensed/raw vendor payloads remain encrypted or outside git. Shared context exposes only redacted/derived/research-safe data already allowed by existing contracts.
- `execution_authorized`, `production_decision_authorized`, and automatic promotion remain false.
- A missing, stale, malformed, or unverified required context is a visible coverage gap, never silently ignored.
- "Accessible" means accessible to the repository/workflow under current credentials, permissions, licensing and technical constraints. Inaccessible scope stays explicit.

## Architecture

### 1. Complete repository inventory

A deterministic generator builds a revision-bound inventory from `git ls-tree -r HEAD`. It records every tracked path, blob identity and size, plus top-level namespace counts/digests. This is the structural proof that all repository surfaces are known even when they are not all loaded into one model prompt.

### 2. Mandatory intelligence surfaces

`config/agent_intelligence_contract.json` declares the research-safe source-of-truth surfaces every unit must know about. The initial contract includes:

- system state/instructions and coordination protocol;
- credential/provider contracts and endpoint catalog;
- provider research context;
- GitHub-native Alpha Vantage, Finnhub and Unusual Whales access receipts;
- SEC EDGAR research context;
- Databento depth research context and depth-test status;
- external EODHD/FMP/Tiingo fabric manifest;
- official economic-event context;
- native-five research status;
- restored-five/control-plane and agent-fabric state;
- flow/microstructure context;
- CL lab/champion/research state;
- data-health sentinel;
- MCP/federation contracts and latest interrepo packet;
- research-allocation/Atlas outputs when present;
- canonical `reppiks490/Icarus` repository revision and federation acceptance;
- owner mission register in `reppiks490/icarus-owner-actions`.

Each item declares whether it is required, optional/conditional, allowed to be stale, and whether missing data means `BLOCKED`, `DEGRADED`, or informational-only.

### 3. Full-system context manifest

`tools/agent_intelligence_context.py` produces `automation_intelligence/agent_context/full_system_context.json` containing:

- exact producer repository and commit;
- complete tracked-tree digest and structural inventory;
- per-surface existence, file/blob digest, selected schema/status metadata and freshness where a source clock exists;
- external repository commit identities and required external document digests;
- explicit gaps with reason codes;
- zero authority flags;
- a canonical `context_id` SHA-256.

The committed manifest contains no plaintext credentials and no raw licensed payloads.

### 4. Agent consumption and acknowledgement

Every interactive worker entrypoint must require reading `AGENT_FULL_CONTEXT.md` and the latest manifest before substantive work. Claude, ChatGPT/Codex and Atlas receive the directive through their native instruction/inbox surfaces.

A unit may state that it used full-system context only if it can name the current `context_id`. Future units use the same rule.

### 5. Automated research lanes

`native-five-research` consumes the full-system manifest. Each Flow/Macro/Aion/Daedalus/Omega receipt records the manifest `context_id`, a bounded summary of shared-data availability, and the exact shared context paths available to the cycle. Omega receives the aggregate gap map so it can prioritize missing evidence rather than reasoning only over public BTC/macro pulls.

The existing lane-specific measurements remain unchanged; shared context supplements them and does not convert collection evidence into a trading claim.

### 6. Federation and cross-repo propagation

`interrepo-peer-intelligence` includes the full-system context manifest as a revision-bound source artifact. Canonical Icarus therefore receives the same context identity and gap state through the existing research-only federation path.

The generator workflow checks out `reppiks490/Icarus` and `reppiks490/icarus-owner-actions` read-only, records their exact revisions, and exposes their declared context documents without granting write or execution authority.

### 7. Gap audit

A scheduled/push workflow runs the generator and test suite. It fails closed when a contract-required surface is absent, malformed, authority-bearing, or cannot be bound to the expected repository revision. Conditional sources remain explicit gaps rather than failing unrelated work.

The data-health sentinel consumes the manifest and reports the count and severity of open context gaps.

## Data flow

1. Existing provider/data workflows collect once and persist redacted/derived outputs.
2. Full-context workflow checks out current Engine plus canonical Icarus and owner-actions.
3. Generator inventories the entire Engine tree, validates all declared intelligence surfaces and records external repo identities.
4. Manifest is committed to `automation_intelligence/agent_context/full_system_context.json`.
5. Interactive agents read it before work; automated lanes receive it as an input; federation exports it to canonical Icarus.
6. Gap state is surfaced to the sentinel and Omega. Missing coverage remains visible until the relevant producer fixes it.

## Failure semantics

- Missing required source: `BLOCKED_REQUIRED_CONTEXT`.
- Missing conditional source: `GAP_CONDITIONAL_CONTEXT`.
- Source schema mismatch: `BLOCKED_SCHEMA_MISMATCH`.
- Authority escalation: `BLOCKED_AUTHORITY_EXPANSION`.
- Source revision mismatch/uncommitted drift: `BLOCKED_REVISION_MISMATCH`.
- Stale source beyond its declared budget: `GAP_STALE_CONTEXT` or blocking if contract marks freshness required.
- External repo unavailable: explicit `GAP_EXTERNAL_REPOSITORY_UNAVAILABLE`; no guessed state.

## Verification

Tests must prove:

- deterministic complete git-tree inventory and digest;
- required/conditional gap classification;
- no secret values or secret-like fields enter manifest output;
- authority flags remain false;
- native-five receipts bind to the same `context_id`;
- interactive instruction files require the manifest;
- interrepo packet includes a verified context witness;
- workflow checks out and binds the two external repositories;
- current production manifest is generated successfully and its remaining gaps match actual unavailable/invalid sources rather than implementation omissions.
