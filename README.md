# Pantograph Client

Async Python client for the custom, explicit-focused Pantograph Lean REPL.
Distribution `pantograph-async-client`, import package `pantograph_async`.

It owns the subprocess, the strict wire codec, state scopes, and cleanup. It
depends only on the standard library and knows nothing about the projects
that use it. A consumer converts the returned execution types into its own
models through a small adapter on its side.

## Install

```bash
pip install "pantograph-async-client @ git+https://github.com/123nol/Pantograph-Client@<commit>"
```

Pin an exact commit. Python 3.11+ on Linux is supported.

Installing the package never downloads or builds a REPL. These are external
prerequisites:

- Lean 4 and Lake on `PATH`, with the toolchain the REPL was built with
  (currently `leanprover/lean4:v4.10.0-rc1`).
- GNU `stdbuf` from coreutils on `PATH`. The uutils `stdbuf` is rejected.
- A compiled custom REPL. Build it from the Pantograph fork with the companion
  patch in this package (see [Compatibility](#compatibility)).
- A Lake project (`source_root`) whose compiled libraries cover the imports
  you request, for example a Mathlib checkout.

## Usage

```python
import asyncio
from pathlib import Path

from pantograph_async import PantographClient, PantographEnv, PantographTacticRejected


async def main():
    env = PantographEnv(
        source_root=Path("/path/to/mathlib4"),
        pantograph_repl=Path("/path/to/Pantograph/.lake/build/bin/repl"),
        imports=("Init",),
    )
    async with await PantographClient.create(env) as client:
        async with client.state_scope() as scope:
            root = await scope.start_goal("∀ (p : Prop), p → p")
            state = await scope.apply_tactic(root, "intro p h")
            goal = state.goals[0]
            print(goal.target.pp, [local.user_name for local in goal.locals])
            try:
                await scope.apply_tactic(state, "exact False")
            except PantographTacticRejected as exc:
                print("rejected:", exc)
        # Leaving the scope deletes every state it allocated.


asyncio.run(main())
```

[examples/minimal_consumer.py](examples/minimal_consumer.py) is the same flow as
a runnable script for an unrelated project.

Key behaviours:

- `PantographClient.create` validates the explicit paths, resolves `LEAN_PATH`
  through Lake, checks `protocol.describe`, and applies the required options
  under one startup deadline. Nothing starts at import time.
- A state scope owns every state it creates. `release` frees one early, and
  leaving the scope frees the rest in one request.
- `start_goal(expr, levels=("u", "v"))` declares the universe parameters the
  expression uses, as Lean's `universe u v` would. Without them a goal such as
  `∀ (α : Type u), α → α` is rejected with `unknown universe level`. Names must
  be atomic ASCII identifiers; the caller maps any other name to a safe alias.
- `apply_tactic(..., goal_index=i)` focuses one goal. Unresolved siblings stay
  in the next state.
- An ordinary rejected tactic raises `PantographTacticRejected` and leaves the
  session usable. Transport, protocol and timeout failures close the session
  and reap the process.
- A transition that introduces `sorry` or an unsafe constant is released and
  rejected. The flags are on `exc.payload.validation`.
- `state.transition` says which goals the tactic produced for the selected
  goal and which are siblings carried over, by execution name.
  `inspect(state, names)` reads obligations a state no longer lists, and
  `certify(state)` has the kernel check the complete root proof. An empty goal
  list is not a certificate.
- Released states can be garbage-collected before the scope exits; the scope
  keeps only a weak reference per live allocation.
- `await_cleanup(task)` awaits a retained cleanup task while deferring the
  caller's cancellation until that cleanup has finished. Worker pools use it to
  shut clients down without leaking processes.

The public API is what `pantograph_async.__all__` exports. Process owners and
the generic wire exchange are private. See [docs/protocol.md](docs/protocol.md)
for the wire contract the codec enforces.

## Diagnostics

```bash
pantograph-client smoke \
  --source-root /path/to/mathlib4 \
  --pantograph-repl /path/to/repl \
  --import Mathlib \
  --report report.json
```

This runs the live protocol checks: instance and let metadata, admission and
unsafe rejection, ordinary failures with source reuse, focused goals and sibling
resumption, independent alternatives, diagnostics and multiline execution, and
at least 100 scoped proofs with a leak check. Imports are used exactly as given.
The diagnostics and unsafe probes are `run_tac` metaprograms, which need `Lean`
(Mathlib imports it). If the imports cannot run them, the command fails rather
than reporting a pass; `--allow-partial` reports them under `skipped_checks`
instead.

The JSON report lists the checks that ran and any that were skipped, the
executable hash, the installed module hashes and source metadata, the descriptor
and compatibility pins, and whether the process was reaped. It reads no files
outside the installed package and needs no Git metadata. An existing report is
never overwritten.

## Compatibility

The client speaks one server contract:

| Field | Value |
| --- | --- |
| `protocol` | `maths-ai-pantograph` |
| `protocolVersion` | 2 |
| `modelSexpVersion` | 1 (`pantograph_async.MODEL_SEXP_VERSION`) |
| `transitionValidationVersion` | 1 |
| `transitionProvenanceVersion` | 1 |
| `inspectionVersion` | 1 |
| `certificationVersion` | 1 |
| `messageVersion` | 1 |
| `goalSelection` | `explicit-focused-v1` |
| `tacticErrorsFormat` | `string-array-v1` |

The wire versions belong to the client. A consumer that derives another
representation from model expressions should compare its own version with
`MODEL_SEXP_VERSION` at startup rather than the client importing it.

The contract, the compatibility manifest and the companion patch ship as
package data:

```python
from pantograph_async import compatibility

compatibility.verify_contract()      # shipped contract == manifest == codec
compatibility.companion_base()       # fork URL, companion commit, base commit, toolchain, Mathlib pin
patch = compatibility.companion_patch()  # bytes, checked against its digest
compatibility.verify_companion_sources("/path/to/Pantograph")  # after applying
```

Check out the Pantograph fork at `companion_base()["source_commit"]`, or apply the
patch to `companion_base()["base_commit"]`, verify the patched files, and build
`repl` with Lake. Lean source development
stays in that fork. [docs/compatibility.md](docs/compatibility.md) has the full
procedure and what each pin means.

## Development

```bash
python -m pip install ".[test]"
python -m pytest
```

The tests run against real child processes, using a diagnostic fake REPL in
`tests/fixtures`. Tests that need a real compiled REPL are marked
`pantograph_live` and skip unless paths are given; `--run-pantograph-live`
turns a missing path into a failure:

```bash
PANTOGRAPH_TEST_SOURCE_ROOT=/path/to/Pantograph \
PANTOGRAPH_TEST_REPL=/path/to/Pantograph/.lake/build/bin/repl \
python -m pytest tests/test_client_live.py --run-pantograph-live
```

The companion checkout itself is a valid `source_root` for these tests, since
they import `Init` and `Lean` (override with `PANTOGRAPH_TEST_IMPORTS`). Set `PANTOGRAPH_TEST_COMPANION_SOURCE` to a
patched checkout to also check its files against the recorded digests.

The sdist carries the complete offline suite with its helpers and fixtures,
the documentation, the extraction evidence, the changelog and the example
(`MANIFEST.in`); the wheel carries only the package. CI builds the sdist, builds
the wheel from it, checks both archives with `scripts/check_sdist.py`, then runs
the tests unpacked from the sdist outside any source tree against the installed
wheel with `PANTOGRAPH_CLIENT_REQUIRE_INSTALLED=1`, so imports must come from
the installed distribution. From a downloaded sdist alone:

```bash
tar -xzf pantograph_async_client-0.2.0.tar.gz
python -m build --wheel pantograph_async_client-0.2.0
pip install pantograph_async_client-0.2.0/dist/*.whl pytest
mkdir suite && cp -r pantograph_async_client-0.2.0/tests suite/ && cd suite
PANTOGRAPH_CLIENT_REQUIRE_INSTALLED=1 python -m pytest -q --rootdir . tests
```

## Releases

See [docs/release.md](docs/release.md) and [CHANGELOG.md](CHANGELOG.md).
Library versions identify releases; protocol and model versions identify wire
semantics, and neither replaces the runtime descriptor check. Consumers pin an
exact commit and upgrade on purpose, re-running their own representation checks.

## License

The code originates in
[Mathematics-ai-atp](https://github.com/iCog-Labs-Dev/Mathematics-ai-atp) and is
distributed under the GNU GPL version 2 text in [LICENSE](LICENSE); see
[NOTICE](NOTICE) for attribution. The companion patch modifies the Pantograph
Lean sources, which keep their own upstream license.
