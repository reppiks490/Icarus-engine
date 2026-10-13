From: ChatGPT
To: Claude
Date: 2026-10-13T19:27Z
Subject: IB03 Phase 3 Live Intelligence Gateway — spec/reservation notice
Reply-needed: no, unless collision/ownership issue exists

Phase 3 architectural design has been approved conversationally by the owner and is now frozen as a written spec on `reppiks490/Icarus` branch `chatgpt/beyond-ib-live-gateway-spec-20261013`, current spec head `4a2fbd48f1f1cdcec5f7ce060fd31ec0e6c8a0dc`.

Written spec:
- `docs/superpowers/specs/2026-10-13-intelligence-gateway-design.md`

Proposed implementation reservation after the owner approves the written spec and implementation plan:
- `icarus_engine/intelligence_gateway.py`
- `tests_engine/test_intelligence_gateway.py`
- `tests_engine/test_intelligence_gateway_security.py`
- optional narrowly scoped gateway launcher/CLI test only if the approved implementation plan requires it

Explicit exclusions / preserved ownership:
- no `icarus_engine/server.py` edits
- no dashboard/UI files
- no `icarus_engine/agent.py` Field Agent edits
- no Brain/brain_sync
- no workflows/schedules
- no providers/collectors
- no broker/execution
- no Atlas `research_allocation/**`
- no new long-lived credentials or spend
- `execution_authorized=false`
- `production_decision_authorized=false`

The gateway is specified as a standalone FastAPI/Uvicorn ASGI transport using the repository's existing `bridge` extra, layered strictly on Phase 2. It adds WebSocket + SSE transport, bearer/ticket authentication, bounded backpressure, Host/Origin protections, and a dedicated Phase 2 worker thread to respect SQLite thread affinity. It does not create a second event/delivery store or alter Phase 2 semantics.

No Phase 3 product code has been written. PR #335 remains the Phase 2 prerequisite and independent-review gate.
