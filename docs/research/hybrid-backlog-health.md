# Full-population hybrid backlog health

`tools/hybrid_loop_bridge.py` derives lane health, oldest unresolved identity and
new requests' `prior_unresolved_request_ids` from every immutable request file.
`latest.json` is a mutable mirror and does not increase the population.

The health record adds `request_count_total`, `unresolved_count_total`,
`invalid_request_count` and `invalid_request_paths`. The unresolved total counts
recognized request identities whose matching result fails the existing
`result_valid` contract; it includes identities with invalid clocks. Files with
unreadable payloads or an identity that does not match their filename appear in
the invalid diagnostics. They cannot be assigned a reliable unresolved identity.
Health requires a valid timezone-aware `requested_at_utc` and, when present,
`request_created_at_utc`, as well as the ordering clock. Any invalid identity or
clock produces `UNVERIFIED`, even when recent requests
all have valid results. A result with a malformed outcome remains unresolved.

Recovery ordering uses timezone-aware `due_slot_utc`, or `requested_at_utc` only
when the due-slot field is absent in an older contract. A present invalid due
slot cannot fall back to another clock. Equal clocks use immutable filenames as
a deterministic tie-break. Unknown clocks are ordered after known clocks and
force `UNVERIFIED`; the reported oldest identity is not a completeness claim
when invalid diagnostics are present.

`unresolved_request_ids_hot_window` and `unresolved_count_hot_window` preserve
their bounded scope: unresolved identities among the latest 24 immutable request
filenames. This view does not determine overall health or recovery provenance.
The public `unresolved_requests` helper retains its explicit `limit` behavior;
the authoritative health and enqueue callers request the entire population.

Existing request/result histories, scheduler state, workflows and execution
authority remain unchanged. A schema-valid `BLOCKED` or `NO_MATERIAL_DELTA`
result resolves the matching protocol obligation under the existing validator;
it does not prove the missing historical work was performed or that any
collection, research or mission requirement is complete.

Run the regression suite with:

```sh
python -m pytest tools/test_hybrid_loop_bridge.py tests_engine/test_hybrid_full_population_health.py -q
```

The tests exercise more than 24 immutable requests, a legacy invalid result
outside a fully resolved recent window, complete prior-recovery identities,
mirror exclusion, byte-preserved histories, malformed requests/results and
aware/legacy/invalid clock ordering.
