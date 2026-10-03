# Peer background Git console repair

Canonical ICARUS #305 suppresses repository-owned Windows child consoles. The
peer repository still omitted that flag in packet-export provenance probes,
watchdog revision/history reads and the MCP contract checker. This repair adds
the same Windows CREATE_NO_WINDOW policy to those noninteractive Git launches.
POSIX options, output capture, stderr routing, return codes and Git source
identity checks remain unchanged. Direct-script and package-module imports both
work; no new dependency or installation is required.

Existing peer #63 was reviewed and integrated before editing the watchdog. Its
four-lane receipt/mirror closure, concurrent-writer rejection and authority
boundaries remain intact. Open #2 is preserved. This changes no schedule, model,
strategy, broker authorization, receipt classification or Git credentials.

Two process-boundary regressions failed before the patch. Afterward, three local
background tests pass and the actual Windows console-API test is skipped on
Linux. Real temporary Git source/history readback and direct-script invocation
pass, as do 26 watchdog unit tests and the three workflow lifecycle tests. The
new Linux/Windows hosted contract must pass before merge, alongside the existing
Python matrix. The same-change MCP interface event reports the repair and its
verification limits for canonical UI consumption.

The user's installed task actions, engine restart and original desktop popup
recurrence remain unobserved. Repository code qualification does not establish
that the user's Windows instance has been updated.
