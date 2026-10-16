# ICARUS coordination — central many-chat bus

This repository's original Claude ↔ ChatGPT board/inbox system is now **historical**. It solved early
collisions, and its messages, boards and lane notes remain useful evidence, but its model-specific task
ownership rules are **superseded** by the central many-chat coordination fabric in
`reppiks490/icarus-owner-actions`.

There is **no model-specific task ownership**. Claude, ChatGPT, Codex, Grok, Atlas, local workers and
future agents may reclaim, divide, review, or cooperate on work when they declare their intent and avoid
undeclared path collisions. A historical Claude or ChatGPT board row is not a permanent lock.

## Canonical coordination every session

Before substantial work, read:

1. `ICARUS_STATE.md`.
2. `reppiks490/icarus-owner-actions:coordination/START_HERE.md`.
3. `reppiks490/icarus-owner-actions:coordination/ACTIVE.md`.
4. `reppiks490/icarus-owner-actions:coordination/collisions.json`.
5. Applicable files under `reppiks490/icarus-owner-actions:coordination/directives/`.
6. `config/data_ingestion_manifest.json`, `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`, and
   `docs/agent-handoffs/DATA_GAP_LEDGER.md` when evidence/data can affect the work.

Create or resume a unique central coordination session. Publish `PLAN` or `CLAIM` before modifying
shared code, workflows, UI, data contracts, or reserved paths. Publish `WAITING` when CI, review,
provider responses, or another dependency is pending; do not go silent while waiting. Publish `UPDATE`
when scope/paths change, `HANDOFF` when another session can benefit or take over, and `COMPLETE` only
with fresh verification evidence.

Reservations are advisory collision prevention, not ownership. If two sessions need an overlapping
path, they must either choose different boundaries or explicitly **cooperate** through mutual
coordination notes. The central compiler reports undeclared repo/path collisions.

Claude is currently inactive by owner direction. Its unfinished work is reclaimable under the central
Claude-reclamation directive. Do not wait for Claude authorization and do not mark its unfinished work
complete merely because Claude is absent.

## Data/evidence federation remains mandatory

Every AI unit must know the complete ICARUS data plane, distinguish credential, ingestion and
consumption state, use applicable live evidence, and keep external blockers explicit. Account-local
connector or secret access is never the authority. Provider or evidence provenance still controls what
can be claimed; the removal of model task gates does not weaken licensing, security, timing, or data
integrity controls.

The historical `board/claude.md`, `board/chatgpt.md`, `inbox/`, `CL_LANE_*.md`, `PR2_*.md`, and
`PEER_*.md` files remain read-only historical/context evidence unless a specific migration task says
otherwise. They may help discover unfinished work, but they no longer determine who may start it.

`tools.coordination` may still be used to inspect those historical boards/inboxes. New work state,
waiting notes, dependencies, reservations and cross-chat handoffs belong in the central
`icarus-owner-actions` coordination bus.

## Continuous cooperation standard

When a test or CI run takes a long time, publish a `WAITING` note naming the run/PR and continue useful
non-conflicting work. When new work is discovered, either build/fix/verify it within the current owner
directive or publish a concrete handoff/blocker. Zero known internal errors is the completion condition
for declared scope; external provider/account/licensing blockers remain explicit.

## Execution boundary

Live broker arming is disabled by current owner direction. Research, replay, paper/shadow execution,
adapters, validation and UI work may continue, but no coordination rule overrides execution gates or
authorizes live trading.
