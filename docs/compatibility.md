# Compatibility

The client supports one validation boundary. `verify_contract()` requires the
codec, current contract resource, compatibility manifest, and companion descriptor
to agree, including the transition validation scope. `companion_base()` checks
that agreement before returning build pins.

## Pinned pair

| Item | Value |
| --- | --- |
| Distribution | `pantograph-async-client` 0.6.0 |
| Client contract revision | 6 |
| Protocol version | 3 |
| Transition validation | 3, `execution-closure-and-representation-aware-audit` |
| Resource and command-transaction versions | 1 |
| Companion commit | `661df4e32bb487f52e4bf229a34b155f9e69c76b` |
| Patch base | `0dd5d2225e2d093f66a4b6231c1aa35004f2c8f3` |
| Patch SHA-256 | `f53b57ee215b35fad7cae684e77eb5c771a246faaecba6eccfe77d96dce73f39` |
| Reference executable SHA-256 | `670c9b058bc2cdb7e85fb81befdf1ee81e6a19ad7744a2d2594cea1262935745` |
| Lean | `leanprover/lean4:v4.10.0-rc1` |
| Native Mathlib source | `29dcec074de168ac2bf835a77ef68bbe069194c5` |
| Platform | Linux, Python 3.11+, GNU coreutils `stdbuf` |

Model expressions, resource errors, command transactions, transition provenance,
inspection and certification keep their previous versions. Protocol version 3
with transition validation version 1 or 2 is incompatible and fails startup. No older
validation decoder or disabled-check option is provided.

## Reproducing the native build

```bash
git clone https://github.com/123nol/Pantograph.git
cd Pantograph
git checkout --detach 661df4e32bb487f52e4bf229a34b155f9e69c76b
python -c "from pantograph_async import compatibility as c; c.verify_companion_sources('.')"
lake build repl test scope_diagnostic compiler_diagnostic
lake test
lake env python3 scripts/test_transactional_resources.py --capture /tmp/resource-exchanges.json
lake env python3 scripts/test_scope_aware_validation.py --capture /tmp/scope-exchanges
```

The CI live job checks out the recorded patch base, applies the bundled patch,
and verifies all 48 changed source hashes before building. It runs the ordinary
Lean tests and both executable harnesses without requiring Mathlib.
Native builds can differ between machines; the recorded binary hash identifies
this tested build, while source verification and the live gate validate rebuilds.

An executable outside a `.lake/build/bin` checkout requires an explicit build
manifest with `toolchain` and `repl_sha256`. Unextended REPLs, protocol versions
1 and 2, Windows and upstream PyPantograph APIs remain unsupported.

## Separate Mathlib client gate

Build the pinned Mathlib source and dependencies separately. The client package
has no runtime or test-install Mathlib dependency. Configure the explicit native
paths when running the client controls:

```bash
PANTOGRAPH_TEST_SOURCE_ROOT=/path/to/Pantograph \
PANTOGRAPH_TEST_REPL=/path/to/Pantograph/.lake/build/bin/repl \
PANTOGRAPH_TEST_COMPANION_SOURCE=/path/to/Pantograph \
PANTOGRAPH_TEST_MATHLIB_ROOT=/path/to/pinned/mathlib4 \
python -m pytest tests/test_client_live.py tests/test_installed_distribution.py \
  --run-pantograph-live --run-pantograph-mathlib
```

The Mathlib option makes missing native paths a failure. Without those paths,
the Mathlib controls skip explicitly. The ordinary core gate still runs all of
its validation, allocation, resource-recovery and certification checks.

The native controls start owned scopes, apply real `tauto` to conjunction,
disjunction and the supplied Finset theorem, inspect retained obligations,
execute alternatives and siblings, certify the original root, and finish with
zero allocations. Dangling executable references remain protocol-integrity
failures that retire the process and invalidate handles.

## Evidence and integration

[Scope-aware provenance](evidence/scope_aware_companion.provenance.json) records
393 native Lean assertions, 17 core and 29 pinned-Mathlib raw exchanges, and the
22-exchange resource harness with its 3,000-request check. A separate capture
applies the client's required serialization options and validates 21 core and
31 Mathlib exchanges through the strict client codec. The compiled Mathlib
identity covers 4,760 `.olean` files and is not a claim of a fresh Mathlib build
or an application environment fingerprint.

Current captures are in `scope_aware_snapshot_companion`, `scope_aware_resources`
and `scope_aware_validation` under `tests/fixtures`. Earlier transactional and
snapshot captures and their provenance remain unchanged as historical evidence.

Stage 3 changes only the standalone client. Application consumers must pin the
reviewed exact client commit, migrate their validation fixtures, and follow the
application and artifact stages in the
[coordinated plan](dev_plans/pantograph_scope_aware_transition_validation.md)
before deployment. No application dependency, checkpoint, inventory, index,
Docker pin, or JupyterHub executable is changed by this package update.
