# Offline retained provider archive consumption

This workflow consumes existing encrypted provider responses. It performs no provider requests,
collection cycles, strategy trials, broker calls, purchases, schedules, or repository writes.
The narrow implementation-branch push trigger permits a native proof before any main merge;
manual dispatch selects only a fixed immutable profile, never caller-supplied code or paths.

## Exact retained sources

All source checkpoints are bound to Engine commit
`84dd20e5186cc26fe4c95a371ea5fbbfed2ecdfe` and their Git blob identity.
Each artifact is bound to its artifact ID, name, SHA-256 ZIP digest, producer run and head SHA.
The workflow validates those identities against GitHub before extracting anything.

| Profile | Producer run | Encrypted artifact ID |
| --- | --- | --- |
| massive | 39184327986 | 12157383656 |
| twelve | 39184327986 | 12157577586 |
| fmp | 39184327986 | 12157607225 |
| eodhd | 39184327986 | 12157801312 |
| tiingo | 39184327986 | 12157781433 |
| fred | 39184327986 | 12157403530 |
| alphavantage supplemental | 39180762048 | 12156341153 |
| alphavantage native | 39166371336 | 12150049222 |

These were retained and unexpired when checked on 2026-10-19. Artifacts expire; expiry is a
hard failure, not permission to acquire replacements. The immutable pin table is in the workflow.
Encrypted checkpoints are fetched from the exact post-cycle source commit, not the earlier
producer workflow's checkout SHA. Native snapshots have no checkpoint binding and say so.

## Privacy and actual use

`tools.provider_archive_intake` supplies the authenticated bounded decoder and creates a new
private extraction tree. Credentials are injected only into the offline intake process. One
selected provider credential is mapped to its existing canonical environment name; no key value
enters arguments, output, artifacts or source files. The optional archive key remains supported.
The Engine base commit `ced31fcfcdf75e4ff2f4181315f462aa5d59a76b` already tracks the canonical
`icarus_engine/security/credentials.py` module and credential contract; no fallback key parser is used.

Socket connection, DNS resolution and connection helpers are blocked inside extraction and
consumption. Raw response values remain in process memory only. Private encrypted downloads,
checkpoint copies and diagnostic logs use restrictive permissions and are removed in an
unconditional final step. Only schema-checked count/hash metadata can be uploaded.
The additional workflow proof binds every output receipt hash to the exact artifact and code pins.

Actual consumers count populated records, scalar/numeric fields, identity and timestamp fields,
explicit asset-identity matches, and corporate-action fields. These are descriptive quality and
binding diagnostics, not signals, training results or proof of profitable trades. Producer-reported
row counts are never promoted to consumed counts. Missing bindings, bad keys, changed hashes,
unsafe ZIP members or bounded resource failures stop the affected job. The implementation's
32 MB encrypted/decompressed/SQLite bounds remain in force; large checkpoints may be unavailable.
Native access never claims checkpoint verification. All receipts deny execution authority,
historical coverage verification and fresh provider access.

## Verification

The workflow contract tests execute input validation and metadata gating, reject mutable refs,
unknown profiles, extra raw-data fields, false authority, invalid hashes and noninteger counts,
and parse every embedded Python and shell program. Root integration must merge the intake
implementation before running this workflow. Native Actions results are separate evidence and
must be recorded after the exact integrated commit runs; local tests alone do not prove that a
real retained archive was successfully consumed.
