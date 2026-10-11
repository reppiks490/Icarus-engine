# Atlas — research decision planning (separate ChatGPT account)

Owner authorized a third, separate worker on 2026-10-11. The original ChatGPT worker is temporarily rate limited, remains owner of its work, and is not replaced. Atlas must never impersonate ChatGPT or acknowledge messages addressed to that worker.

## Owns

New paths only: `research_allocation/**`, this board, and new messages with sender `atlas`.
No ownership of strategy science, research trials, claims certification, integration acceptance, collectors, runtime, UI, workflows, shared protocol/tooling or the other boards.
Potential semantic overlaps go to the existing owner before implementation.

## Tasks

| Id | Task | Status | Branch / PR | Updated |
|---|---|---|---|---|
| AT01 | Metadata-only dependency planner: minimal missing-evidence bundles, counterfactual unblock impact, owner routing | waiting | [Engine141](https://github.com/reppiks490/Icarus-engine/pull/141), prototype tested; peer scope/code review pending | 2026-10-11 |
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
