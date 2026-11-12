# RT01 flatten status correction — 2026-10-15T23:40Z

The RT01 real-price shadow twin merged as Icarus PR #361 at `ff684e6ae1062f072e32f7cdb60826ba615044f7`.

A follow-up branch, `codex/rt01-http-status` at `cfcea78e1dbf2ea931c84780bd754e12265f4073`, handles missing/nonfinite marks as structured HTTP 409 responses in the workspace command-center flatten route, preserving the open-position and pause state in the response. Local focused execution/shadow/evidence/workspace tests pass, and the independent UI review found the command-center finding resolved with no new issue. This commit is after the merged PR and has not yet been submitted as a new PR; shadow execution remains unauthorized and default-off.

Current active review: Icarus PR #377, head `98c53108ac04b602788361b5c6e114a6252888ed`, adds per-asset RT01 dashboard metrics. Focused JS/shadow tests passed locally (87 tests); all checks except browser CI have passed. Independent review is in progress.
