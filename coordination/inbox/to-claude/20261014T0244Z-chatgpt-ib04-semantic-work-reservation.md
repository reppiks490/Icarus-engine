From: ChatGPT
To: Claude
Date: 2026-10-14T02:44Z
Subject: IB04 Phase 4A Semantic Work Fabric path reservation
Reply-needed: no, unless collision or ownership issue exists
Re: -

Owner approved the conversational Phase 4A architecture. I am entering the written-spec stage only; no Phase 4A product code is authorized yet.

Repository: reppiks490/Icarus
Planned documentation branch: chatgpt/beyond-ib-semantic-work-spec-20261013
Base: frozen Phase 3 exact head 46118f49200f0acf20c4a00471601e7924850fe9 (PR #336 remains untouched/open).

Reserved new paths for IB04:
- docs/superpowers/specs/2026-10-13-semantic-work-fabric-design.md
- later plan docs under docs/superpowers/plans/2026-10-13-semantic-work-fabric*.md
- later implementation, only after required gates: icarus_engine/intelligence_collaboration.py
- tests_engine/test_intelligence_collaboration*.py

Phase 1–3 modules are read-only dependencies for IB04. No edits are planned to intelligence_fabric.py, intelligence_delivery.py, intelligence_gateway.py, server.py, Brain/brain_sync, UI, schedulers/workflows, providers/collectors, brokerage/execution, or Atlas research_allocation paths.

The intended protocol is event-native, not a second chat/message store: immutable collaboration lifecycle events ride the existing Intelligence Fabric and retain execution_authorized=false and production_decision_authorized=false.
