# Match the live gate to the transactional REPL

Status: approved and implemented, 2026-11-04. Native gate passes against
published companion commit `5cab95e132bcdd1d3cb715505d1694ac7bb0e0d6`.

Implementation evidence is recorded in
[transactional companion provenance](../evidence/transactional_companion.provenance.json).
The patch reproduces 32 changed source files; a clean build passes 351 Lean
assertions. Fresh captures contain 22 resource/recovery exchanges, the raw
harness covers 3,000 repeated requests, and the client native gate passes.
Final validation against the installed wheel built from the sdist: 759 passed,
1 optional historical-binary skip, 0 deselected. This uses the sdist's own tests,
includes all native tests, and verifies zero runtime dependencies. Archive and
whitespace checks pass. Hosted CI has not been rerun with this repair.
The native heartbeat test now imports the companion's reduction fixture; its
previous `run_tac` loop did not exhaust the command budget. Native fatal shutdown
is also checked through the client. CI builds the Lean test target, runs its
assertions and raw harness, then runs the required client live gate.

Sandbox process/thread exit notifications stall locally. Running the unchanged
client suites outside the sandbox resolves this, including the previously
stalled cross-event-loop tests. No timeout assertions were relaxed.

## Failure and scope

GitHub Actions run `41887309565` builds the bundled historical companion patch
and invokes the native tests. The executable reports protocol version 2. The
client requires version 3 and rejects the missing `resourceErrorVersion` and
`commandTransactionVersion` fields during `protocol.describe`.

The live gate is detecting an incompatible client/server pair. This change must
coordinate the package's reproducible companion build and native evidence.

The local fork `/home/nolawi/pantograph_fork` contains transactional companion
commit `5cab95e132bcdd1d3cb715505d1694ac7bb0e0d6`. Its protocol also removes
`printJsonPretty`; compact JSON framing is mandatory. Updating just the patch
would therefore expose another startup mismatch in `options.print`.

## Chosen architecture

1. Verify the companion commit, tracked source cleanliness, toolchain, build
   inputs, and executable identity. Preserve unrelated untracked fork files.
   Check publication status before claiming a reproducible published source pin.
2. Derive the bundled patch from the committed companion sources against the
   documented base. Check that applying it in an isolated checkout reproduces
   every recorded source digest. Update compatibility pins, patch digest, source
   digests, binary identity, and provenance together.
3. Remove `printJsonPretty` from shared required/allowed options, current contract
   resources, authored fixtures, fake server, examples, and current documentation.
   Audit every caller by symbol search. Preserve historical captures unchanged.
   Reject the removed option through the strict request schema.
4. Import the companion's shared resource schema and fixtures as attributed
   contract evidence. Validate the Python codec against native exchanges for
   commands it exposes. Capture fresh snapshot and recovery exchanges against
   the exact rebuilt executable, including source-state reuse, certification,
   zero final allocations, fatal termination, and cumulative-request coverage.
5. Run the existing native client suite against the rebuilt companion. Confirm
   that the heartbeat probe actually exhausts the command budget and returns
   the expected rolled-back envelope. Adjust the probe to the companion's
   documented deterministic mechanism if needed, preserving its assertions.
6. Keep the CI live job required and preserve strict descriptor checks. Audit
   its base-plus-patch reconstruction and update it only where the coordinated
   build requires a change. Run offline, native, wheel, sdist, and installed
   distribution checks. Record evidence and any remaining external gates.

Application resource-outcome migration and deployment remain separate delivery
work. This repair establishes standalone client/REPL compatibility.

## Alternatives considered

| Approach | Benefits | Limitations | Decision |
| --- | --- | --- | --- |
| Match companion sources, schemas, pins, and native tests | Restores reproducible native verification | Requires a real build and caller migration for the removed option | Chosen |
| Disable or skip the live gate | Quickly removes the failing check | Leaves the installed client unable to use the bundled companion | Reject |
| Accept protocol version 2 or add error-parser fallbacks | Allows the historical executable to start | Cannot establish transactional resource recovery | Reject |
| Only update the companion patch | Addresses the first descriptor failure | Leaves obsolete options and provenance inconsistent | Reject |
| Revert the revision-3 feature | Restores the earlier matched pair | Removes the requested resource-recovery support | Reserve only for an explicitly requested rollback |

## Verification gate

The user's supplied AGENTS.md required explicit verification after architecture
drafting and before the deep fix. The user approved this repair and supplied the
published companion commit before implementation began. Application migration
and deployment remain external delivery work.
