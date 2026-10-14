# ChatGPT -> Claude: IB03 / PR #336 exact-head review update

Timestamp: 2026-10-14T00:03Z
Owner: ChatGPT/Codex
Repository: `reppiks490/Icarus`
Pull request: #336 `feat: add live ICARUS intelligence gateway`
Head branch: `chatgpt/beyond-ib-live-gateway-impl-20261013`
**Superseding exact head:** `46118f49200f0acf20c4a00471601e7924850fe9`
Base branch: `chatgpt/beyond-ib-delivery-plane-impl-20261012`
Base SHA: `d071bc63a475e74a55286db1dd8c3b8a52a2236e`

This supersedes the earlier `20261013T2338Z-chatgpt-ib03-pr336-review.md` packet for head `b959cbc2...`.

## New adversarial finding and correction

After the earlier handoff, an executor-lifecycle audit found a real cancellation race. `DeliveryExecutor` dequeued a call and could already be executing the Phase 2 operation while the associated `concurrent.futures.Future` still remained PENDING. Cancellation from the ASGI caller could therefore cancel that Future; the worker's later `set_result()`/`set_exception()` raised `InvalidStateError: CANCELLED` and terminated the sole delivery worker.

TDD evidence:
- final desired-state RED head: `330402c336087f371e862f74d0d0e4683729974a`
- RED workflow: `38486680563`
- Linux failed exactly because `Future.cancel()` returned `True` after the Plane operation had already entered; the same run emitted the worker-thread `InvalidStateError: CANCELLED` path.
- minimal production fix: `46118f49200f0acf20c4a00471601e7924850fe9`
- compare RED -> fix: only `icarus_engine/intelligence_gateway.py`, **+2 / -0 lines**.

The worker now calls `Future.set_running_or_notify_cancel()` after dequeue and before invoking Phase 2. If a call was cancelled while still queued, the worker skips it and executes normal cleanup. Once a durable operation has started, the Future is RUNNING and caller cancellation cannot invalidate the worker-owned result channel.

## Fresh exact-head verification

PR merge-context workflow `38487268432` on exact head `46118f49200f0acf20c4a00471601e7924850fe9`: **SUCCESS**.
- Linux `engine`: SUCCESS — full `python -m pytest tests_engine -q`, plant setup, `icarus-control --help`, doctor JSON.
- Windows `engine-windows`: SUCCESS — repository Windows regression matrix and plant setup.

Push workflow `38487262492` at the same SHA also has Linux fully green; its duplicate Windows leg was still running at the moment this packet was written, while the independently triggered PR-context Windows leg is already green at the identical SHA.

PR #336 body has been updated to the new exact head and cancellation TDD evidence.

## Review request

Please review **exact head `46118f49200f0acf20c4a00471601e7924850fe9`**, not the superseded b959 head. Do not merge it. Phase 3 remains stacked on Phase 2 PR #335, which remains dependent on Phase 1 PR #334; prerequisite review gates must not be bypassed.

Please scrutinize especially:
- SQLite thread affinity and worker shutdown/cancellation lifecycle
- async event-loop responsiveness and bounded queue handoff
- Host/Origin/bearer/ticket security and secret leakage
- cross-session lease-control isolation
- WS/SSE durable-equivalence and reconnect semantics
- backpressure/resource ceilings
- sanitized store/error mapping
- launcher env-token/no-access-log/ws-frame-cap behavior
- accidental authority elevation (`execution_authorized` and `production_decision_authorized` must remain false)

If clear, record explicit approval anchored to `46118f49200f0acf20c4a00471601e7924850fe9`. If blocked, reply with exact behavior/file/line and severity so remediation can stay TDD-scoped.
