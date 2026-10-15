# Bounded five-failure investigation — declared before runs

Timestamp: 2026-10-03. NEW_REAL_MODEL_STARTS=0.

Round A: original adjacent file order, one run each of the complete guided-first-delivery geometry parameter group followed by the complete large-pack-timeout-settlement file. Instrumentation only first: stdout/stderr/return code + marker/times and preflight transition traces. No other GUI/build/test workload during this baseline. This establishes a quiescent comparison to the archived full-suite concurrent-GUI run; the archived run remains FAIL and lacks lower-level timestamps.

Round B (only after A evidence): one deterministic bounded fault-control per confirmed measurement hypothesis (delayed iframe message; delayed workspace preparation versus boundary read). Preserve assertions. Do not label historical timing root cause proven merely because A passes. Maximum two diagnostic rounds per hypothesis. A new failure is captured, investigated once; unresolved causes remain UNKNOWN and gate BLOCKED. No repeated full suites.

After evidence-backed fixes, one associated integration group. Final complete suite only after frozen source, artifact and packaged GUI checks, serial with no GUI/build work. Preserve all runs, XML and exit codes. A full failure cannot be replaced by five isolated passes.

## 2026-10-03: test-runner permission fault, bounded correction

The external evidence runner set `umask(077)` for private log creation and
unintentionally passed it to pytest. Existing synthetic delivery manifests
explicitly require source mode `0644`; the runner created `0600` files. The run
was normally interrupted after 1016 passed / 200 failed (exit 2), and remains
INCOMPLETE, not a complete regression result. Its log, XML, source fingerprints
and diagnostic captures are retained separately. No Owner process was stopped.

One predeclared two-arm comparison ran the same three candidate/apply/history
tests under each mask: 077 produced 3 failures with source mode 0600; 022
produced 3 passes with mode 0644. No assertion or product safety check changed.
The corrected runner keeps its evidence parent/files private while explicitly
using the normal 022 mask only for the isolated pytest child. This is a
test-harness fix, not an assertion that every failure has independently been
explained. The corrected full run must still exercise all cases.

The cleanup-durability assertion is also strengthened to use the actual platform
temporary root, instead of assuming `/private/tmp`, and require the product's
REMOVED status. No test manually copies a model reply to make persistence pass.
Neither test nor runner change alters any of the 78 build inputs of 101.18.

Bound: after the independent artifact readback, execute exactly one corrected
complete suite with this input, no concurrent GUI/build or other suite. Any new
failure is retained for diagnosis; there is no retry-until-green loop. The
original 101.17 FAIL and the interrupted 101.18 run remain intact. Historical
browser causes without original diagnostics remain UNKNOWN even if current
checks pass.

## Post-full-run bounded diagnostic correction

The corrected complete run finished with 1467 passed / 1 failed / 1 skipped,
exit 1. The failure is pack_dialog-1280: communicate timed out at 10 seconds,
SIGTERM was requested, the five-second drain also timed out, and SIGKILL of
that isolated process group raised EPERM before diagnostic writing. Why the
OS denied that signal is not established. This does not prove a layout error
or reconstruct either historical missing-marker case.

Bound declared before the next checks: one deterministic fault-control file
against the old harness, then an exception-capture-only harness change, then
one run of that same file. No additional complete suite or repeated actual
browser group this round. Preserve EPERM/timeout as failure; do not bypass
permissions, increase deadlines, or accept partial DOM as a passing run.
The correction must preserve bounded partial output and UNKNOWN exit status
in finally, close only owned pipe handles, and propagate the original failure.
It changes test diagnostics only; all packaged inputs remain frozen. The
complete FAIL remains authoritative and the offline gate remains BLOCKED.
