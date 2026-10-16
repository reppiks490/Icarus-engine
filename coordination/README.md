# ICARUS Engine coordination compatibility layer

This directory preserves the original Claude ↔ ChatGPT boards, inboxes, lane notes, and handoffs that
were created before the federation moved to a model-neutral many-chat coordination fabric. Keep these
records for provenance. They are historical evidence and compatibility inputs, **not current task
ownership or write locks**.

## Canonical coordination authority

All new work is coordinated through `reppiks490/icarus-owner-actions`:

- `coordination/START_HERE.md` — mandatory bootstrap for every chat/agent;
- `coordination/ACTIVE.md` — generated live work view;
- `coordination/collisions.json` — generated target-collision view;
- `coordination/owner_status.json` — owner-level availability and safety constraints;
- `coordination/directives/**` — standing operating directives and reclaim queues;
- `coordination/sessions/**`, `events/**`, and `summaries/**` — machine-verifiable work records.

Before mutating this repository, publish a central PLAN/CLAIM event with repo-qualified targets and
check the compiled collision state. No model family owns a task merely because an older local board
listed it. If old Claude/ChatGPT work is unfinished, compare it with current `main`, open PRs, and the
central state; then reclaim, cooperate, supersede, or publish the exact blocker.

## What remains authoritative locally

1. Read `../ICARUS_STATE.md` for Engine technical facts, verified results, failed ideas, and authority
   boundaries.
2. Read `../config/data_ingestion_manifest.json`,
   `../docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`, and
   `../docs/agent-handoffs/DATA_GAP_LEDGER.md` before data/provider claims.
3. Preserve evidence provenance, provider licensing boundaries, fail-closed behavior, and exact-head
   verification. Account-local connector/secret access is not federation authority.
4. Live broker arming follows central `owner_status.json` and is currently disabled.

## Legacy boards and mailboxes

- `board/claude.md` and `board/chatgpt.md` are historical snapshots. They may contain useful unfinished
  requirements, branches, PRs, or evidence references, but they do not gate who may work them.
- `inbox/to-claude/**`, `inbox/to-chatgpt/**`, and `inbox/to-atlas/**` remain immutable historical
  messages once on main. New cross-chat communication belongs in the central event fabric.
- `python -m tools.coordination` may still be used to inspect legacy records where helpful; it is not
  the source of current work ownership.
- Older lane notes (`CL_LANE_*.md`, `PR2_*.md`, `PEER_*.md`) remain historical evidence unless a
  current central event explicitly adopts their requirements.

## Operating rule

Do not idle merely because one target is reserved or CI is running. Publish the waiting/dependency
state, then continue with useful non-conflicting research, tests, review, documentation, or another
claimed subproblem. Complete work only with exact evidence and a durable central summary.
