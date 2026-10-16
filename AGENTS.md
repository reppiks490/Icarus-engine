# Instructions for every coding agent (Codex, ChatGPT, Claude, others)

Read `ICARUS_STATE.md` first. It is the local technical source of truth for this repository: goals,
verified results, dead ideas, data access, safety boundaries, and research/execution authority. Update
it when a fact changes and never contradict it without correcting it.

## Central ICARUS coordination is mandatory

Work coordination is model-neutral. No task, package, file, provider, or research question is reserved
because a particular model family historically handled it. Before substantial work, every chat/agent
must use the canonical coordination bus in `reppiks490/icarus-owner-actions`:

1. Read `coordination/START_HERE.md`, `coordination/ACTIVE.md`, `coordination/collisions.json`,
   `coordination/owner_status.json`, and applicable `coordination/directives/**` there.
2. Create/resume a unique central session and publish a `PLAN` or `CLAIM` event **before mutation**.
   Reserve narrow repo-qualified targets (`repo` + `path`), then re-read the compiled collision state.
3. Same-target work is allowed only after explicit mutual cooperation is recorded by the involved
   sessions. A reservation is a coordination lease, not permanent ownership.
4. Publish `UPDATE`, `WAITING`, `BLOCKED`, `HANDOFF`, `RELEASE`, and evidence-backed `COMPLETE` events
   as the work state changes. Waiting on CI/review/provider work is not a reason to stop useful,
   non-conflicting work.
5. Before ending a workstream, push the work, publish exact evidence (PR/head/run/test/artifact or
   external blocker), and create a durable central summary so old event chatter can be safely pruned.

The legacy `coordination/board/**` and `coordination/inbox/**` records in this repository are preserved
for provenance and historical handoffs. They are **not task locks** and do not prevent another model or
chat from reclaiming unfinished work after checking current main, open PRs, and the central collision
state. `coordination/README.md` documents the compatibility boundary.

## Shared data/evidence plane

Before claims about provider access, source coverage, freshness, market evidence, or blockers, read:

- `config/data_ingestion_manifest.json`
- `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`
- `docs/agent-handoffs/DATA_GAP_LEDGER.md`
- `automation_intelligence/sentinel/data_health.json`
- `automation_intelligence/manifest.json`

Account-local connectors or secret visibility are never federation authority. Do not print, copy,
commit, artifact, or move plaintext credentials. Do not relabel missing/denied data as success.

## Safety / execution boundary

Live broker arming is controlled by the owner status in the central bus and is currently disabled.
Research, replay, simulation, shadow, and paper infrastructure may continue within verified scope, but
no agent may enable live-order authority merely because broker/provider code exists.
