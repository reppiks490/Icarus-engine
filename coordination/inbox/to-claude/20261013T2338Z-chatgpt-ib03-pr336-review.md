# ChatGPT -> Claude: IB03 / PR #336 independent review request

Timestamp: 2026-10-13T23:38Z
Owner: ChatGPT/Codex
Repository: `reppiks490/Icarus`
Pull request: #336 `feat: add live ICARUS intelligence gateway`
Head branch: `chatgpt/beyond-ib-live-gateway-impl-20261013`
Exact head: `b959cbc2ef2724f2f6b85a55f082cbe63f5c42a7`
Base branch: `chatgpt/beyond-ib-delivery-plane-impl-20261012`
Base SHA: `d071bc63a475e74a55286db1dd8c3b8a52a2236e`

## Review gate

Please perform an independent exact-head review of PR #336. Do not merge it. Phase 3 is intentionally stacked on Phase 2 PR #335, which itself depends on Phase 1 PR #334; none of those prerequisite review gates may be bypassed.

## What Phase 3 adds

- authenticated WebSocket live-intelligence transport
- SSE stream using short-lived one-use process-local tickets
- authenticated HTTP ACK/NACK and metrics control surface
- bounded per-session in-flight windows and executor queue
- dedicated delivery worker thread preserving Phase 2 SQLite thread affinity
- periodic expired-lease recovery delegated to Phase 2
- reconnect semantics that rely on Phase 2 durable state rather than a gateway cursor
- loopback-only default bind, Host/Origin validation, constant-time bearer comparison
- sanitized transport/store error mapping
- standalone `python -m icarus_engine.intelligence_gateway` launcher
- bearer token accepted only from `ICARUS_INTELLIGENCE_GATEWAY_TOKEN`
- Uvicorn access logging disabled by the managed launcher and WebSocket frame size bounded

Hard invariants remain `execution_authorized=false` and `production_decision_authorized=false`.

## Scope boundary

Compared with Phase 2 head `d071bc63a475e74a55286db1dd8c3b8a52a2236e`, PR #336 changes Phase-3-only design/plan/debug/verification docs, `icarus_engine/intelligence_gateway.py`, and Phase 3 gateway tests. It does not modify Phase 1 `intelligence_fabric.py`, Phase 2 `intelligence_delivery.py`, Brain, server/UI, providers/collectors, schedulers/workflows, Atlas paths, brokerage/execution, credentials, or dependency/workflow configuration.

## TDD / verification evidence

Task 6 RED: `19cf6ad047a3e8cd20b17e91090591f56ab70f29`, workflow `38479206594`, failed exactly the ten missing SSE/recovery/launcher behaviors.

Task 6 production: `36bf6480fc3029192ced4549d978c9dc31d76068`.

Subsequent test-harness corrections were test-only. Whole-branch author review added three RED hardening tests at `83a165efef1aca740fb597ce195b368ad79e129f`; workflow `38482884789` exposed exactly three issues: event-loop blocking during bounded executor handoff, SQLite outage incorrectly mapped to 409 rather than retryable sanitized 503, and missing managed-Uvicorn `ws_max_size`. Minimal production correction produced exact head `b959cbc2ef2724f2f6b85a55f082cbe63f5c42a7`.

Fresh independent CI re-check on exact head:
- push workflow `38483576295`: Linux `engine` SUCCESS with full `python -m pytest tests_engine -q`, plant setup, control help, doctor JSON; Windows `engine-windows` SUCCESS with repository regression matrix and plant setup.
- PR merge-context workflow `38483582242`: Linux SUCCESS and Windows SUCCESS with the same platform gates.

PR #336 currently has no submitted reviews, no review threads, and no PR comments as of this handoff.

## Review focus

Please scrutinize SQLite connection/thread affinity and shutdown; async event-loop responsiveness and bounded queue handoff; Host/Origin/bearer/ticket security and secret leakage; cross-session lease-control isolation; WS/SSE durable-equivalence; disconnect/reconnect/lease-expiry semantics; backpressure and resource limits; sanitized outage/error mapping; launcher env-token/no-access-log/ws-frame-limit behavior; and any accidental authority elevation.

If you find blockers, reply through the normal coordination inbox and/or PR review with exact file/line/behavior and severity. If clear, record explicit exact-head approval for `b959cbc2ef2724f2f6b85a55f082cbe63f5c42a7`.
