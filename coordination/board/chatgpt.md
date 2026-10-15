# ChatGPT / Codex — task list

Edited only by ChatGPT/Codex. Protocol: `coordination/README.md`.
Owner resumed under refinements A–F on 2026-10-11. No spend, new credentials,
schedule/automation changes or execution activation; execution_authorized=false.
Read-only review does not transfer package ownership.

## Owns

- C01–C03, `reppiks490/Icarus`: `icarus_engine/brain.py`,
  `tests_engine/test_brain.py`, `icarus_engine/unusual_whales_intake.py`,
  `tests_engine/test_unusual_whales_intake.py`. Integrate C01 → C02 → C03;
  Claude reviews each code PR before merge. Draft backup does not imply completion.
- J01-consumer, `reppiks490/Icarus`: `icarus_engine/brain_sync.py`,
  `tests_engine/test_brain_sync.py`, `tests_engine/test_brain_historical_context_gate.py`,
  and `tests_engine/fixtures/federation_v2/**` once the corrected spec is approved.
- C04, `reppiks490/Icarus-engine`: `automation_intelligence/hybrid_loop_fabric_v1/**`
  and request/result contracts. Additional code/workflow edits require bounded
  reservations; existing lane cadences/settings remain unchanged.
- M01/M02/J02-originals/S01 evidence, `reppiks490/icarus-owner-actions`:
  `mission/register.json`, `mission/compiler.py`, `tests/test_mission_compiler.py`,
  `mission/continuations/**`. Append scoped evidence, preserving original history.
- X1-Codex, `reppiks490/Icarus-engine`: this board and new immutable files under
  `coordination/inbox/to-claude/`; Atlas replies use its documented [Atlas]
  fallback in `coordination/inbox/to-chatgpt/` until registration merges.
  Claude owns protocol/tooling; each worker edits only its own board.
- C05/J03, P01, U01, E01: reserve specific files before implementation. Preserve
  Icarus visual/mobile PR318/198, historical PR295 and other owners' open changes.
- IB01, `reppiks490/Icarus`: new backend-only `icarus_engine/intelligence_fabric.py`,
  `tests_engine/test_intelligence_fabric.py`, and its Superpowers design/plan docs.
  Phase 1 does not edit Brain, brain_sync, server, workflows, execution, UI or Atlas registry paths.
- IB04, `reppiks490/Icarus`: new backend-only `icarus_engine/intelligence_collaboration.py`,
  `tests_engine/test_intelligence_collaboration*.py`, and its Superpowers design/plan docs.
  Phase 4A treats Phase 1–3 as read-only dependencies and does not edit gateway, delivery, fabric,
  Brain, server, UI, workflows, providers, execution or Atlas registry paths.
- A200 specification only, `reppiks490/Icarus`: `docs/superpowers/specs/2026-10-15-market-universe-200-contract.md`.
  This does not claim `icarus_engine/assets.py` or feed adapters until the parallel asset worker's
  current files and interface are confirmed.
- BKR specification only, `reppiks490/Icarus`: `docs/superpowers/specs/2026-10-15-broker-propfirm-integration-contract.md`.
  This does not claim `icarus_bridge/brokers/**`, executor, config or UI paths until the parallel agent's
  vendor/account list and current reservations are confirmed.

Confirmed hand-overs: Claude owns Engine J01 specification/contract/fixtures/producer,
K1 provider collector/workflow/tests, acquisition/vault/depth/SEC source health,
CL strategy science, and Engine state/instruction files. Codex owns Icarus consumer,
Brain, original archive verification, hybrid lane contracts, mission evidence and
functional runtime. The owner reserved UI, aesthetics and animations for
Claude Code on2026-10-11. On2026-10-13 the owner made animation upgrades against
the newest Dropbox upload the immediate Codex priority. Codex is auditing the
reference and browser baseline and proposing new choreography files; Claude
Code's existing UI files and unpublished work remain preserved. The owner's renewed UI direction was implemented through isolated files and two
additive hooks whose current-main base and final diff were independently reviewed.
No unpublished Claude Code changes were available to inspect or overwrite. Atlas owns
research_allocation/** and its owner-transferred Icarus discovery-registry
foundation (AT04) paths; no Brain/J01/mission/collector ownership transfers.
Codex reviews Claude's changes; Engine rules affecting Codex require
its review. Engine PR84 overlaps Claude's CL lane and stays open/intact pending a
concrete preservation/port agreement. No broad historic namespace claim overrides
these hand-overs. No research trials were run in this resumed Codex session.

## Tasks

| Id | Task | Status | Branch / PR | Updated |
|---|---|---|---|---|
| X1-Codex | Board/replies delivered in138; refreshed reviews and Atlas replies | in progress | codex/coordination-atlas-resume-20261011 | 2026-10-11 |
| IB01 | Beyond-IB intelligence fabric: durable causal event bus, semantic threading, deterministic priority and replay/query over Unified Intelligence | in progress | chatgpt/beyond-ib-intelligence-fabric-20261012 | 2026-10-12 |
| IB04 | Beyond-IB Phase 4A Semantic Work Fabric: machine-verifiable work requests/responses, deterministic lifecycle projection, evidence/delegation/challenge semantics over immutable Intelligence Fabric events | in progress | chatgpt/beyond-ib-semantic-work-spec-20261013 | 2026-10-13 |
| RT01 | Real-price shadow twin v1: default-off, mirrored Pulse intents, standard-bar emulator, per-asset/portfolio read-only metrics; broader attribution remains follow-up | in progress | [Icarus361](https://github.com/reppiks490/Icarus/pull/361), head09283239; exact-head CI pending, 7 focused tests pass | 2026-10-15 |
| A200 | Write the source-qualified 200-asset/feed contract; runtime/catalog integration waits for the parallel worker's current files and interface | in progress | `reppiks490/Icarus: docs/superpowers/specs/2026-10-15-market-universe-200-contract.md` | 2026-10-15 |
| BKR | Define the broker/proprietary-firm connection contract and exact coverage evidence; implementation waits for the parallel agent's vendor/account inventory and file reservations | in progress | `reppiks490/Icarus: docs/superpowers/specs/2026-10-15-broker-propfirm-integration-contract.md` | 2026-10-15 |
| C01 | Reviewed clock validation merged; exact-head Linux/Windows and merged readback pass | done | [Icarus329](https://github.com/reppiks490/Icarus/pull/329), merged3ae97b4d4f0228e6e815c3dd59cd02e0986c50f0; reviewed head282db0d9 | 2026-10-11 |
| C02 | Draft backup published; Windows fixture correction; integrate after C01 | in progress | [Icarus330](https://github.com/reppiks490/Icarus/pull/330), head8b7cf387d23b3e6043304b501db5a107aff10da6; integrated on merged C01, original4f85e135 preserved | 2026-10-11 |
| C03 | Original draft backed up; integrate after C02 | waiting | [Icarus331](https://github.com/reppiks490/Icarus/pull/331), headda3357f155717fc3cf265c2afe10b7893e963060; original609a67c8 preserved | 2026-10-11 |
| J01-consumer | Implement legacy-four/complete-modern-six consumer; pin v2 fixtures and exact-head test | waiting | [Icarus339](https://github.com/reppiks490/Icarus/pull/339): Linux/Windows green; peer review and Engine producer contract remain; live gate fails closed | 2026-10-14 |
| C04 | Full-population reconciliation delivered; recovery/invalid-result disposition await owner action | waiting | [owner-actions14](https://github.com/reppiks490/icarus-owner-actions/pull/14): 939 immutable requests; 5 valid BLOCKED, 934 unresolved | 2026-10-14 |
| C05/J03 | Useful licensed Unusual Whales source-to-consumer qualification | planned | Icarus328 intake merged; dependent on C02 integration | 2026-10-11 |
| J02-originals | Authenticate original archives; lawful restoration, full coverage and point-in-time qualification | planned | ZIP/ciphertext preservation and owner-actions11 complete within scope | 2026-10-11 |
| M01 | Oct11 continuation delivered; append later receipts without inflated credit | in progress | [owner-actions12](https://github.com/reppiks490/icarus-owner-actions/pull/12), merged4e2fb9dc; frozen register unchanged | 2026-10-11 |
| M02 | Component acceptance, independent leakage review and traceability/certification | planned | owner-actions mission; no global success claim | 2026-10-11 |
| S01 | Containment re-review passes; rights and history exposure remain unresolved | waiting | [Engine135](https://github.com/reppiks490/Icarus-engine/pull/135), approved97677bef; owner-actions12 exposure receipt | 2026-10-11 |
| P01 | Master Pump identity, delivery, restart and truthful observability | planned | reserve bounded repository-qualified paths first | 2026-10-11 |
| U01 | Original sculpted cosmic choreography, complete opening timing and scoped interaction polish merged; browser and engine verification complete within stated limits | done | [Icarus337](https://github.com/reppiks490/Icarus/pull/337), head7d502ea3; mergedb6aa7333 | 2026-10-14 |
| E01 | Measured architecture experiments and verified transfer | planned | define hypothesis, baseline and bounded paths first | 2026-10-11 |
| DB84 | Keep original intact; agree P2/P3, defer P1 under no-automation-change limit | waiting | [Engine84](https://github.com/reppiks490/Icarus-engine/pull/84), open head8ad1d7eb08305011a43d32dc0c696bc0bd69ecdf | 2026-10-11 |
| MAX-Pine | Parked; preserve source/design/plan and incomplete original transport | waiting | max-pine-implementation add4d62211aadfa09924db589842c9bb94943c20 | 2026-10-11 |
| L5-preserve | Preserve existing owner loops/settings; no automation mutation | waiting | historical reported states not freshly verified here | 2026-10-11 |

## Evidence and limits

- Canonical owner-actions register at d7034d9879d4c6dc5aa96a4bb7591008493ca133:
  202 frozen requirements, 200 DISCOVERED, 2 IMPLEMENTED_UNVERIFIED,
  0 VERIFIED, 0 INTEGRATED. Bounded component receipts do not certify full requirements.
- Reviewed Claude135/136/137 exact heads db3835da/12c1c4f5/3c4fd65b:
  each had twelve green checks; all received one consolidated blocking review comment.
  Independent tests:135 32 passed,136 31 passed, zero failed/skipped.
  PR137 scientific review ran no research trials.
- C01 requires Claude's PR-thread exact-head review, even though four CI checks were green.
  Published tree equals the preserved local C01 tree.
- C02 four-file diff SHA2566d7bcf0ec8399fdb29c09b0b5da756b2d2bb799813d1ac194aa81b97a7d21495:
  113 focused,88 dependent,92 additional tests passed; zero failed/skipped.
  Linux results do not prove Windows intake coverage. Draft publication is not completion.
- C03 fresh original-base Brain suite:60 passed, zero failed/skipped;
  integrated C02-base rerun remains required.
- Full hybrid audit at f4c803ad06ec2f512fdc69b9c3b10c817270b039 on2026-10-11:
  658 requests,6 exact-identity results,5 valid BLOCKED;653 unresolved
  (652 missing,1 invalid Alpha NO_MATERIAL_DELTA). No MATERIAL_DELTA credit.
  Oct9 counts478/473 are historical and are not current.
- S01: current-tree encrypted containment does not erase plaintext history since
  Sep20 branch/Oct10 main or establish redistribution rights. No history rewrite.
- Original archive transport preservation is complete within hash/CRC scope;
  usable authenticated lawful corpus, eligible denominator and consumer readback remain unproven.
- MAX two exact blobs preserve an incomplete XZ stream and decoded Pine prefix,
  not a complete authenticated original. Keep branches/design/plan intact.

## Latest resumed-session receipts (2026-10-11 evening UTC)

- Engine138 merged889612dc4bef7b21d51845d8272102067cdc68a3 after twelve passing
  exact-head checks; all three files matched merged readback. owner-actions12
  merged4e2fb9dc59b101425b45c9b9278b1210973e4db9 after three passing checks and
  23local compiler tests; all six new continuation files matched branch readback.
- Claude approved C01 on its PR thread at282db0d9. Integrated main26c0e01+C01:
  82tests passed,0failed/skipped. Rerun38147165599 passed Linux/Windows; merged3ae97b4d and both files matched readback.
- Re-review135 at97677bef:41tests passed,6exact-head checks green; origin/inventory
  corrections and authenticated thirteen-file physical runner restore accepted.
- Re-review136 atd69c95c1:57fixture tests pass, but typed metadata, malformed IDs,
  clock/nonfinite exceptions and live legacy-summary bounds remain blockers.
- Re-review137 at72f5bdb8: intraday roll availability, null interval ordering and
  trial identity/full-family DSR accounting remain blockers; no research trials run.
- Atlas registration143 at5216a4ee:11focused tests+5synthetic checks pass,
  twelve exact-head checks green; peer review approved. Native routing awaits
  merge; historical fallback remains manual, not delivery certification.
- C02 original Windows failure was a CRLF fixture; explicit-byte fixture follow-up
  preserves production and strict assertions. Fresh5boundary+113focused tests
  pass onLinux; genuine current-head Windows validation remains pending.

- C02 integrated8b7cf387:175tests collected/passed,0failed/skipped; Claude
  PR-thread review requested. Full current-head CI remains pending.
## U01 animation reference scope (2026-10-13)

- User requested extensive animation upgrades to match the newest Dropbox upload.
  Dropbox setup is confirmed, but its file tools are not exposed in this running
  session; direct reference access remains pending. No reference has been viewed
  and no product animation change is claimed.
- Read-only baseline pinned to Icarus1b1a35a403a80f7dd9d2d02387909647af23d731.
  Preserve UI318 at aab4a4f78d6e7a83fd35961239a0b47ed5ea16e0 and the existing
  ui-evolution-day3 branch at a72509e2; neither establishes Claude Code's latest work.
- Proposed bounded Codex reservation, once the reference and split are established:
  reppiks490/Icarus: icarus_engine/reference-choreography.js,
  icarus_engine/reference-choreography.css,
  tests_engine/browser_reference_choreography.cjs,
  docs/ui/REFERENCE_CHOREOGRAPHY.md. These new paths are not product edits yet.
- Ask Claude for Claude Code's latest branch/pin and an agreed hook in dashboard.html
  plus the exact server.py asset allowlist. Do not overwrite broad experience CSS,
  world modules, subsystem UI or artwork without a specific split.
- Seven private Chromium captures passed desktop/mobile/reduced-motion checks:
  no page/console errors or horizontal overflow, four navigation tabs active,
  cinematic canvas changes and reduced motion stops DOM/canvas/GPU activity.
  All39requests used local assets or labelled synthetic empty-engine fixtures;
  populated charts and similarity to the reference remain unverified.
- Verification will compare actual motion with the reference, cover desktop/touch,
  reduced motion, scene lifecycle, frame times and read-only behavior. Existing
  backend packages remain saved and do not transfer to another worker.

## U01 reference available and implementation claim (2026-10-13T05:12Z)

- Dropbox file tools are available in this new turn. Retrieved the newest root
  upload, Video Oct12 2026,9 12 14PM.mov (uploaded2026-10-13T04:46:37Z),
  42,780,477bytes. Original local file is unchanged; Dropbox content hash matches
  583f3ae95875307ca16d2dd85ca0e614a107737826ac0a78bb8fba809a29dc1a.
  Visual analysis of its22.84second timeline supersedes the earlier access blocker.
- Codex claims new Icarus files: icarus_engine/reference-choreography.js and .css,
  tests_engine/reference_choreography_lifecycle.cjs,
  tests_engine/test_reference_choreography.py, and docs/ui/REFERENCE_CHOREOGRAPHY.md.
  They implement original procedural nebula material, dark depth contours with
  luminous rims and coherent camera/light motion using existing motion lifecycle.
- dashboard.html script/style includes and server.py's exact static-asset tuple
  are proposed narrow integration hooks in an isolated PR. Do not merge them
  around Claude Code's unpublished UI changes; peer review must establish the
  current integration base. Broad existing UI files, world modules and artwork
  are preserved. No source video/frame/audio enters public git.
- Design targets cinematic scenery with readable text, reduced-motion/offscreen
  stops, bounded GPU resolution and graceful unavailable/lost-context fallback.
  Existing dashboard controls/data/execution/automation/registry behavior is outside
  this change. Shader output is an original approximation of the reference's
  visual language, not a claim of matching authored anime production in full.

## U01 delivered (2026-10-14)

- Icarus337 merged b6aa7333933dd67bbec747fe76949324e8bfc306 from reviewed head
  7d502ea31b1ef814987368730d424e82f76cf290. All seven merged files match readback.
- Full local suite: 2,184 passed, 3 Windows-only skips, 90 subtests passed; no errors.
  Six focused pytest cases include 23 Node lifecycle cases. All 12 exact-head
  Linux/Windows engine, contract and config checks pass.
- The full private reference was studied before the final material pass. Real
  Chromium verified all themes, four viewport widths, context recovery, stop gates
  and a natural opening reaching 98.7% before removal. All 14 captures have zero
  overflow; 108 requests were local synthetic GETs; no page/console/shader errors.
- Receipt: coordination/inbox/to-claude/20261014T1650Z-chatgpt-u01-animation-receipt.md.
  Synthetic fixtures do not prove live data or hardware FPS; Windows CI's explicit
  list omits the new test module. Film-production equivalence is not claimed.
- Earlier U01 access/blocker paragraphs are historical and superseded. Broader
  UI/artwork/other-agent reservations and backend review gates remain preserved.
