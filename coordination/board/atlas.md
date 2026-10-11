# Atlas — research decision planning (separate ChatGPT account)

Owner authorized a third, separate worker on 2026-10-11. The original ChatGPT worker is temporarily rate limited, remains owner of its work, and is not replaced. Atlas must never impersonate ChatGPT or acknowledge messages addressed to that worker.

## Owns

New paths only: `research_allocation/**`, this board, and new messages with sender `atlas`.
No ownership of strategy science, research trials, claims certification, integration acceptance, collectors, runtime, UI, workflows, shared protocol/tooling or the other boards.
Potential semantic overlaps go to the existing owner before implementation.

## Tasks

| Id | Task | Status | Branch / PR | Updated |
|---|---|---|---|---|
| AT01 | Metadata-only dependency planner: minimal missing-evidence bundles, counterfactual unblock impact, owner routing | in progress | [Engine141](https://github.com/reppiks490/Icarus-engine/pull/141), prototype tested; peer scope/code review pending | 2026-10-11 |
| AT02 | Third-worker registration in coordinator, owned by Claude; request via existing inbox | waiting | 20261011T1547Z-atlas-registration-and-scope.md | 2026-10-11 |

## Operating agreement

- Advisory only. No strategy tests, market-data reads, parameter tuning, trial-ledger writes, provider calls, spend, credentials, scheduling changes or trading authorization.
- Infer dependencies only from cited documents; distinguish reported from independently verified evidence. Never turn planned work or passing CI into a proven strategy.
- Unknown costs remain unknown; structural unblock count is not expected return, information gain or scientific proof.
- Existing workers own approval and execution of recommendations. Do not pre-empt their review or blocked tasks.
- Read both original boards and current inboxes before each session. Add immutable `atlas` messages to existing inboxes; replies may use `to-chatgpt` with `Subject: [Atlas]` and an exact `Re:` until Claude supports `to-atlas`.
- `tools/coordination.py` currently hard-codes two identities; Atlas is NOT automatically counted or scheduled. Documentation presence is not delivery acknowledgement.
- No continuous work between interactive turns is claimed.

## Evidence and decisions

Initial snapshot: Engine main bb736a898fc8803d212f410c7e7f783430bd7ae1.
Read ICARUS_STATE, AGENTS, coordination README, both boards, all three to-chatgpt messages, roadmap, coordination tool, CL watch/hypotheses, R5 and D1 preregistrations.
Searches for value_of_information and experiment allocation returned no matches; information gain found existing per-source depth acquisition prioritization. This supports a bounded gap hypothesis, not proof of novelty across every branch.
Chosen scope: cross-workstream decision prerequisites, complementary to per-source collection selection. Rejected takeover, general audit and new strategy research because those are already assigned.
Knowledge delta is contained in this board, research_allocation/README.md and immutable peer messages. Existing routers are owned by peers; ask their owner to add Atlas rather than modify them.

## Deeper investigation, 2026-10-11

Correction: direct inspection of Icarus 0bf06e98c9fbda627116578f8686a178e6837d68 found existing APEX information ranking, CapabilityGraph, TheoryLibrary and Omnivision's budget-allocation design. Search absence was not reliable. Atlas must reuse these, not claim a novel generic governor. Proposed next scope is derivation/validation of decision value from predictive models and costs, inside the existing isolated namespace. No runtime/E01 or scientific work claimed. See [POTENTIAL.md](https://github.com/reppiks490/Icarus-engine/blob/15cad18d02636c3da94238d87bc971e5fef89c0e/research_allocation/POTENTIAL.md) and synthetic potential_probes.json in PR141; functionality is proposed and peer review remains pending. Four bounded synthetic behavior probes completed; no market research run.

## Owner-authorized implementation, 2026-10-11T15:58Z

User explicitly requested a substantial build and ongoing peer communication while the other models reset. AT03 now in progress within research_allocation/**: finite outcome-model decision value; unknown costs and sensitivity scenarios; explicit joint observations; offline CLI and prospective SQLite recommendation/outcome journal. No existing runtime or scientific-policy ownership transfers. Knowledge delta: README.md, DESIGN.md, examples/, tests, and verification record in this namespace. All inputs synthetic or owner-supplied metadata; no market evaluation, spend or new schedules.

## Canonical registry handoff, 2026-10-11T21:01Z

AT04 in progress. The owner explicitly supplied the stopped worker's screenshots and authorized Atlas to continue the approved Icarus discovery-registry foundation. Exact handoff: feat/capability-data-discovery-registry-foundation at b882078d6442af6d4ca674d572450009b004bffe; Tasks 1–5 complete, resume Task 6. Live branch and successful CI run38168706850 match. This is a bounded transfer of the registry task, not replacement of the other ChatGPT account or ownership of Brain/UI/J01/collectors.

Reserved in reppiks490/Icarus only: icarus_engine/discovery_registry/**; tests_engine/test_discovery_registry_*.py and fixtures/discovery_registry/**; tools/catalog_registry_ingest.py; tests/test_catalog_registry_ingest.py; config/catalog_registry_sources.json; .github/workflows/catalog-registry-refresh.yml; scoped .gitignore, README.md and docs/icarus/CAPABILITY_DATA_DISCOVERY_REGISTRY.md; a scoped execution/handoff record. Existing provider acquisition code remains read-only. Code stays on the implementation branch/PR; no main merge, deployment, paid call, trading authority or workflow activation.

AT03 research_allocation implementation is preserved locally and in draft PR141; adapter and global trial-ledger integration remain unclaimed. Claude's 19:22Z scope review and registration PR143 were read; no reply is being sent as the original ChatGPT worker. Atlas will use immutable [Atlas] messages in to-chatgpt until registration merges. Task updates are deliveries, not acknowledgement or peer approval.

## AT04 implementation checkpoint, 20261011T213350Z

Draft [Icarus333](https://github.com/reppiks490/Icarus/pull/333), checkpoint 022a40fa1a60f770657d3d3d34caf1aece6d6d0d: Tasks 6–11 implemented in the reserved canonical-registry scope. Independent review defects have fifteen RED/GREEN regressions; 113 targeted registry/CLI/provider tests passed. Final full suite and corrective re-review pending. No main merge, activation or peer-owned runtime edits. AT03 remains preserved and separate. Both peers received immutable 20261011T213350Z-atlas-registry-checkpoint.md; delivery is not acknowledgement.

## Verified AT04 / resumed AT03, 2026-10-11T21:42Z

Original ChatGPT's three 21:07Z replies have been read: AT04 reservation acknowledged with no concurrent writer, isolated explicit-model scope accepted, and runtime adapters still unclaimed. Registration PR143 remains Claude's merge decision; manual [Atlas] fallback is still used.

AT04 implementation is complete awaiting peer/human review of draft Icarus333. Current local reviewed code a432943: 116 targeted tests, full engine2,229 passed/3skipped/90subtests, independent review CLEAR. Published predecessor022a40fa CI38176831346 succeeded; final corrective publication/CI and immutable evidence record follow. Connector-pinned v3 input imports4,131 scraping +153 AI entries,4,284 entry links and2,740 candidates; malformed/non-entry rows and unsupported URLs stay audited. This is not production HTTP or source qualification.

AT03 resumes publication of the existing finite-model implementation within research_allocation/**. Per Claude's PR141 review comment6112774338, reserve one new collection shim tests/test_research_allocation.py so the existing pytest CI actually collects the synthetic tests; no workflow or runtime change. Local standalone suite69passed before publication. Add accurate DESIGN/README/verification, preserve the original metadata prototype and source snapshots. Local SQLite journals remain outside git; exports are text, advisory records are not a second scientific trial ledger. Peer review/real-world validation are still required, no adapter or research launch.
