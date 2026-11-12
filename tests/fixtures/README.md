# Test fixtures

Wire evidence from successive companion builds. Historical captures are never
rewritten to describe a newer executable. Current success responses must carry
validation version 3; earlier descriptors and validation metadata are rejected.

| Path | What it is | Accepted by the codec |
| --- | --- | --- |
| `baseline/` | Raw capture from the original, unmodified custom REPL | No |
| `upstream_pr1/` | Live capture from the merged fork (PR #1) without the companion patch | Failure variants only |
| `historical_revision1/` | Authored fixtures for the superseded contract revision 1 | No |
| `historical_revision2/` | Authored fixtures for contract revision 2 (protocol version 1) | No |
| `stage4_companion/` | Live capture from the Stage 4 companion build (protocol version 1) | Failure variants only |
| `snapshot_companion/` | Live capture from the snapshot companion build (protocol version 2), with its provenance | Non-transition operations only; descriptor and version-1 transitions rejected |
| `future_contract.json` | Authored contract-revision-6 responses used by the fake REPL and codec tests | Yes |
| `fake_repl.py` | Diagnostic child process for real-process transport tests; never used at runtime | n/a |

Canonical graph goldens belong to the consuming application, not here.

`transactional_snapshot_companion/` records historical protocol-version-3, validation-version-1 snapshot
and options exchanges. `transactional_resources/` carries the exact shared
error schema/fixtures from companion commit `5cab95e`, plus fresh raw executable
recovery exchanges. Artifact hashes and the source/binary identity are recorded
in `docs/evidence/transactional_companion.provenance.json`. Historical captures
are preserved unchanged.

Current evidence uses the `recursion_depth_*` directories, captured from
companion `91dbc0f` in the same way as the `compiler_aware_*` directories below.
They add native recursion-depth rollback exchanges and resource details version 2.
The `failure_diagnostics_*` directories (companion `661df4e`,
`docs/evidence/failure_diagnostics_companion.provenance.json`) and the
`compiler_aware_*` ones (`docs/evidence/compiler_aware_companion.provenance.json`)
are history.

The `compiler_aware_*` layout:

- `compiler_aware_snapshot_companion/`: snapshot and options exchanges, source pin,
  binary identity, certification and zero-allocation cleanup.
- `compiler_aware_resources/`: unchanged shared resource schema/fixtures and fresh
  native resource exchanges against the validation-version-3 executable.
- `compiler_aware_validation/`: exact shared validation schema/fixtures from
  `fc740c2`, fresh core and Mathlib exchanges, including compiler-producing
  tactics (`unfold Nat.pow`, `rw [Nat.pow]`, `simp only [Nat.pow]`) and their
  certificates, owner/residue diagnostics and pinned Mathlib source
  verification. `capture.json` preserves the raw harness default serialization
  options. `client_capture.json` enables client-required model expressions and
  is checked by the full response decoder.

`docs/evidence/compiler_aware_companion.provenance.json` records the matched pair
and artifact hashes.

The `scope_aware_*` directories are the validation-version-2 evidence from
companion `ba2c3dd`, recorded in `docs/evidence/scope_aware_companion.provenance.json`.
They and the other prior directories retain their original bytes and identities.
