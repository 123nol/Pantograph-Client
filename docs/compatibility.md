# Compatibility

`src/pantograph_async/resources/compatibility.json` is the machine-readable
manifest; `pantograph_async.compatibility` reads it through the installed
package.

## What is pinned

| Item | Value |
| --- | --- |
| Contract revision | 3 (descriptor in [protocol.md](protocol.md)) |
| Pantograph fork | `https://github.com/123nol/Pantograph.git` |
| Base commit | `0dd5d2225e2d093f66a4b6231c1aa35004f2c8f3` (the patch reproduces branch `client_centric_repo`) |
| Companion patch | `repository_client_contract.patch`, SHA-256 `18689e1c99335648706f0aa2e2aedebd4fc4b06fd89b648a51fd6a770554d96b` |
| Lean toolchain | `leanprover/lean4:v4.10.0-rc1` |
| Tested Mathlib | `29dcec074de168ac2bf835a77ef68bbe069194c5` |
| Platform | Linux, Python 3.11+, GNU coreutils `stdbuf` |

The manifest also lists the SHA-256 of every file the patch produces
(`patched_sources_sha256`) and the hash of the originally validated binary
(`reference_repl_sha256`). Native Lean builds are not bit-reproducible across
machines, so a rebuilt `repl` is checked by its source digests and the live
smoke, not by that reference hash.

## Reproducing the companion REPL

```bash
git clone https://github.com/123nol/Pantograph.git
cd Pantograph
git checkout --detach 0dd5d2225e2d093f66a4b6231c1aa35004f2c8f3
python -c "from pantograph_async import compatibility as c; import sys; sys.stdout.buffer.write(c.companion_patch())" | git apply -
python -c "from pantograph_async import compatibility as c; c.verify_companion_sources('.')"
lake build repl
pantograph-client smoke --source-root . --pantograph-repl .lake/build/bin/repl --import Lean
```

Start from a clean checkout. Do not apply the patch over local changes or over
a downloaded archive. Mathematics AI's `setup_sexpr_environment` script does
these steps, refuses modified checkouts, and records the identities in a build
manifest.

An executable outside a `.lake/build/bin` checkout needs an explicit
`build_manifest` JSON with `toolchain` and `repl_sha256`.

## Not supported

Other Pantograph releases, the upstream PyPantograph API, Windows, and REPLs
without the companion validation metadata. An unextended REPL fails at
`protocol.describe`.

## Historical evidence

`docs/evidence/snapshot_companion.provenance.json` records the build behind the
current patch. `docs/evidence/repository_client_contract.provenance.json` is the
original Stage 4 provenance record, kept unchanged. Its absolute paths describe the
machine where it was captured and are not required locations.
