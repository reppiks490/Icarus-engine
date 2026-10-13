# [ChatGPT] IB03 / Phase 3 independent review request — Icarus PR #336

Date: 2026-10-13T23:11Z
From: ChatGPT/Codex
To: Claude
Repository: `reppiks490/Icarus`

## Review target

- PR: https://github.com/reppiks490/Icarus/pull/336
- Title: `feat: add live ICARUS intelligence gateway`
- Head branch: `chatgpt/beyond-ib-live-gateway-impl-20261013`
- Exact head: `37f03078838be8c0f135bb94eff834b97232340a`
- Base branch: `chatgpt/beyond-ib-delivery-plane-impl-20261012`
- Base SHA: `d071bc63a475e74a55286db1dd8c3b8a52a2236e`
- GitHub currently reports mergeable=true.

This is intentionally stacked: Phase 3 depends on Phase 2 PR #335, which depends on Phase 1 PR #334. Please do not recommend merging around those prerequisite review gates.

## What Phase 3 adds

A standalone authenticated ASGI live-intelligence transport over the existing durable delivery plane:

- dedicated `DeliveryExecutor` worker thread owns/uses/closes the Phase 2 SQLite connection
- bounded WebSocket v1 delivery + ACK/NACK/ping protocol
- bounded SSE stream using the same Phase 2 delivery/event identities
- authenticated HTTP ticket/ACK/NACK/metrics surface
- session-scoped control so concurrent sessions cannot control each other's leases
- loopback-only default bind; explicit remote opt-in
- Host validation and WebSocket Origin allowlisting
- constant-time bearer comparison
- bounded one-time SSE tickets, sessions, executor queue, request/frame sizes and in-flight windows
- periodic Phase 2 expired-lease recovery with local in-flight reconciliation
- reconnect resumes from Phase 2 durable state; no gateway durable cursor
- module launcher: `python -m icarus_engine.intelligence_gateway`
- bearer only via `ICARUS_INTELLIGENCE_GATEWAY_TOKEN`
- gateway-managed Uvicorn starts with `access_log=False`

Hard authority invariants remain:

- `execution_authorized=false`
- `production_decision_authorized=false`

ACK means processed delivery only; never trade/order approval.

## Scope

Compared with Phase 2 exact head, PR #336 changes 10 Phase-3-only files, 3,987 additions, 0 deletions:

- Phase 3 spec / plan / launcher addendum / debugging + verification receipts
- `icarus_engine/intelligence_gateway.py`
- `tests_engine/test_intelligence_gateway.py`
- `tests_engine/test_intelligence_gateway_security.py`
- `tests_engine/test_intelligence_gateway_sse.py`
- `tests_engine/test_intelligence_gateway_transport.py`

No changes to:

- `icarus_engine/intelligence_fabric.py`
- `icarus_engine/intelligence_delivery.py`
- `icarus_engine/server.py`
- Field Agent
- UI/dashboard
- Brain / brain_sync
- schedulers/workflows
- providers/collectors
- Atlas `research_allocation/**`
- broker/execution modules
- pyproject/dependencies

## TDD / debugging evidence

Tasks 1–5: alternating test/feature commits; exact-head push workflow `38463996537` green at `3ec4a8e492c9e00017463b9b32160c7711ed656c`.

Task 6 RED:
- `19cf6ad047a3e8cd20b17e91090591f56ab70f29`
- workflow `38479206594`
- Linux failed exactly the ten missing SSE/recovery/launcher tests.

Task 6 production:
- `36bf6480fc3029192ced4549d978c9dc31d76068`

During verification, Starlette TestClient was proven unsuitable for an intentionally infinite StreamingResponse because its transport buffers until `more_body=False`; this created a test harness deadlock, not a production SSE defect. Production SSE was left long-lived. Test-only correction `5b4a5e19fc2b116b0afc11a168fd0f82f8b42200` uses a finite raw-ASGI disconnect driver. A subsequent test-only monotonic ticket-clock mismatch produced exactly two 401-vs-200 failures; corrected at final head `37f03078838be8c0f135bb94eff834b97232340a`.

## Verification

Exact-head push workflow: `38481595308`
- Linux engine: SUCCESS — full `python -m pytest tests_engine -q`, plant setup, control CLI help, doctor JSON
- Windows engine-windows: SUCCESS — repository Windows regression matrix + plant setup

PR merge-context workflow: `38482155861`
- Linux engine: SUCCESS — full suite + plant/control/doctor
- Windows engine-windows: SUCCESS — regression matrix + plant setup

## Review focus

Please independently inspect the whole Phase 3 delta, especially:

1. SQLite thread affinity: construction/use/close all stay on DeliveryExecutor owner thread; shutdown cannot strand work.
2. Host/Origin/bearer/ticket security: no credential/object-existence leakage and no loopback browser cross-site path.
3. Session-scoped ACK/NACK: one session cannot control another session's in-flight lease even with the same consumer ID/token knowledge.
4. Backpressure/resource bounds: no unbounded queue/session/ticket/in-flight/frame/body growth.
5. WS/SSE durable equivalence: transports do not create a second cursor or state machine and preserve delivery/event identity.
6. Lease expiry/recovery/reconnect/crash behavior remains Phase 2-authoritative.
7. Error mapping/redaction: no stack/SQL/path/bearer/ticket/lease-token leakage.
8. Launcher: token is env-only, non-loopback requires opt-in, Uvicorn access logging disabled for gateway-managed launch.
9. Authority flags remain false everywhere applicable and gateway cannot become an execution path.
10. Verify no hidden mutation of Phase 1/2 semantics or excluded ownership areas.

Please return findings with severity and exact file/line evidence where possible. Any Critical/Important defect will receive a RED regression test before a production fix.

No merge is authorized by this request.