# ICARUS Cross-Repository Evidence Federation

Every AI unit working anywhere in ICARUS must treat the repository family as one evidence fabric. Repository boundaries control write ownership; they do not permit an AI to ignore evidence produced elsewhere.

The machine-readable repository ledger is `config/federated_repo_evidence.json`. Read it together with `config/data_ingestion_manifest.json`, `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`, `docs/agent-handoffs/DATA_GAP_LEDGER.md`, `automation_intelligence/manifest.json`, and current Sentinel health before making system-wide claims.

## Repository roles

- `reppiks490/Icarus-engine` is the canonical GitHub-native data/source/health plane.
- `reppiks490/Icarus` contains runtime consumers, source-qualified runtime evidence, the private metadata-only Unusual Whales intake, and remains the preferred provider owner for Intrinio under the bounded failover contract.
- `reppiks490/divine-providence` contributes Research Institution and Observatory evidence. Its Institution independently observes official Federal Reserve, ECB, and SEC announcement feeds and owned CSV corpora.
- `reppiks490/icarus-csv-evidence-lab` contributes Advanced CSV persisted evidence, history, heartbeat/finalization, and restored-five liveness/durability receipts.
- `reppiks490/icarus-causal-router` contributes deterministic synthetic causal-research assurance only. It is not live market validation or provider-access evidence.
- `reppiks490/icarus-owner-actions` contributes mission-register governance, acceptance, and continuation evidence; its offline consistency workflow is not a market-data collector.

Each auxiliary repository now contains an `AGENTS.md` pointer to the canonical ICARUS federation state so an AI entering that repository directly receives the same rule set.

## Mandatory behavior

Every AI unit must consume relevant cross-repository evidence before declaring a subsystem complete, healthy, trained, validated, source-covered, or production-ready. If the current unit cannot access a repository or connector, record that capability blocker explicitly rather than silently dropping the evidence family.

Do not copy plaintext credentials between repositories or AI accounts. GitHub Actions Secrets/Variables remain the credential authority; provider receipts, dedicated manifests, specialist heartbeats, and Sentinel health are the runtime-evidence authority.

Do not collapse evidence classes. Synthetic causal assurance is not live-market proof; governance records are not provider data; a heartbeat is not proof of downstream consumption; a stored key is not proof of authentication or entitlement.

The standing completion condition is zero known ICARUS-owned gaps. External provider/account/licensing/network blockers stay explicit until the external dependency changes.
