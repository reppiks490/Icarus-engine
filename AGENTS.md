# Instructions for every coding agent (Codex, ChatGPT, Claude, others)

Read `ICARUS_STATE.md` first. It is the single source of truth for this repository: goals, verified
results, dead ideas, data access, ownership boundaries and the rules no agent may break. Update it when
a fact in it changes, and never contradict it without correcting it.

## Mandatory many-chat coordination

ICARUS no longer gates tasks to a model family. Claude, ChatGPT, Codex, Grok, Atlas, local agents and
future workers coordinate through the canonical many-chat bus in `reppiks490/icarus-owner-actions`.
There is **no model-specific task ownership**; reservations exist to prevent accidental path collisions,
not to permanently lock work to a model.

Before substantial work, read:

- `reppiks490/icarus-owner-actions:coordination/START_HERE.md`
- `reppiks490/icarus-owner-actions:coordination/ACTIVE.md`
- `reppiks490/icarus-owner-actions:coordination/collisions.json`
- applicable `reppiks490/icarus-owner-actions:coordination/directives/*`
- this repository's `coordination/README.md`

Create or resume a unique coordination session. Publish a `PLAN` or `CLAIM` before modifying shared
code, workflows, UI, data contracts, or other reserved paths. Publish `WAITING` while CI, review,
provider responses, or dependencies are pending; publish `UPDATE` when scope changes; publish `HANDOFF`
when another worker can use or take over a subproblem; publish `COMPLETE` only with fresh verification
evidence. If another session reserves an overlapping path, choose another boundary or explicitly
cooperate; never silently overwrite it.

Claude is currently inactive by owner direction. Its unfinished work is reclaimable under the central
Claude-reclamation directive after a takeover/cooperation note. Absence is not completion and no worker
should wait for model-specific authorization.

## Shared ICARUS data/evidence truth

For work affected by market, provider, macro, depth, filing, specialist, public-market, or research
evidence, also read:

- `config/data_ingestion_manifest.json`
- `config/federated_repo_evidence.json`
- `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`
- `docs/agent-handoffs/DATA_GAP_LEDGER.md`
- `automation_intelligence/sentinel/data_health.json`
- `automation_intelligence/manifest.json`

Credential presence, workflow existence, and downstream consumption are separate facts. Never copy
plaintext credentials into chats, code, logs, artifacts, coordination notes, or another account.
External provider/account/licensing blockers remain explicit; they are not relabeled as fixed.

## Execution boundary

**Live broker arming is disabled** by current owner direction. Research, replay, paper/shadow execution,
adapters, validation, and UI may be built and tested, but do not arm live broker execution, bypass
execution gates, or reinterpret paper connectivity as live authorization.

A slow CI or provider dependency is not a reason to go silent. Record the `WAITING` state in the central
bus and continue useful non-conflicting work where possible. Before stopping, make the latest state,
paths, dependencies, blockers and verification evidence visible through the coordination bus.
