# Compatibility

The installed `compatibility.json` manifest records the descriptor, companion
source, bundled patch and native executable identity. `verify_contract()`
requires the codec, contract resource, manifest and companion descriptor to agree.
`companion_base()` performs that check before exposing build pins.

## Pinned companion

| Item | Value |
| --- | --- |
| Client contract revision | 4 |
| Wire protocol | 3; resource-error and command-transaction versions 1 |
| Pantograph fork | `https://github.com/123nol/Pantograph.git` |
| Companion commit | `5cab95e132bcdd1d3cb715505d1694ac7bb0e0d6` |
| Patch base | `0dd5d2225e2d093f66a4b6231c1aa35004f2c8f3` |
| Patch SHA-256 | `0914f6587b1d31ab1a293bb68f6ff911726f5adc609e9e4cc7e64f867865dd79` |
| Reference executable SHA-256 | `1c29397e4c0e9d3af499b6d18872cf9562c64fde3fc4c0bc59cec5494c772f30` |
| Lean toolchain | `leanprover/lean4:v4.10.0-rc1` |
| Historical tested Mathlib pin | `29dcec074de168ac2bf835a77ef68bbe069194c5` |
| Platform | Linux, Python 3.11+, GNU coreutils `stdbuf` |

The new native checks import `Init`, `Lean` and `Test.ContractFixtures`. They do
not establish Mathlib or application acceptance. Native builds can differ by
machine; source hashes and the live gate validate a rebuilt executable.

## Reproduction

```bash
git clone https://github.com/123nol/Pantograph.git
cd Pantograph
git checkout --detach 5cab95e132bcdd1d3cb715505d1694ac7bb0e0d6
python -c "from pantograph_async import compatibility as c; c.verify_companion_sources('.')"
lake build repl test
lake test
lake env python3 scripts/test_transactional_resources.py --capture /tmp/resource-exchanges.json
pantograph-client smoke --source-root . --pantograph-repl .lake/build/bin/repl --import Lean
```

CI checks out the patch base, applies the bundled patch and verifies every
recorded changed-file digest before building. This produces the same sources
as the pinned companion commit without relying on a moving branch.

An executable outside a `.lake/build/bin` checkout requires an explicit build
manifest with `toolchain` and `repl_sha256`. Protocol versions 1 and 2, unextended
REPLs, Windows and upstream PyPantograph APIs remain unsupported. Revision 3
removes `printJsonPretty`; every response is one compact JSON line.

## Evidence and delivery

[Transactional provenance](evidence/transactional_companion.provenance.json)
records the clean build, 351 native assertions, 22 raw recovery exchanges,
3,000 repeated requests, and native client results. Current snapshot captures
are in `tests/fixtures/transactional_snapshot_companion`; shared schema, error
fixtures and recovery captures are in `tests/fixtures/transactional_resources`.
Earlier snapshot and Stage 4 captures and provenance remain historical evidence.

Delivery order remains companion publication, matched client validation and
release, complete application migration, then a controlled deployment restart.
No Docker or JupyterHub executable is replaced by this package repair.
