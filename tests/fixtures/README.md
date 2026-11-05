# Test fixtures

Wire evidence from successive companion builds. Historical captures are never
rewritten to describe a newer executable. Current success responses must carry
validation version 2; earlier descriptors and validation metadata are rejected.

| Path | What it is | Accepted by the codec |
| --- | --- | --- |
| `baseline/` | Raw capture from the original, unmodified custom REPL | No |
| `upstream_pr1/` | Live capture from the merged fork (PR #1) without the companion patch | Failure variants only |
| `historical_revision1/` | Authored fixtures for the superseded contract revision 1 | No |
| `historical_revision2/` | Authored fixtures for contract revision 2 (protocol version 1) | No |
| `stage4_companion/` | Live capture from the Stage 4 companion build (protocol version 1) | Failure variants only |
| `snapshot_companion/` | Live capture from the snapshot companion build (protocol version 2), with its provenance | Non-transition operations only; descriptor and version-1 transitions rejected |
| `future_contract.json` | Authored contract-revision-5 responses used by the fake REPL and codec tests | Yes |
| `fake_repl.py` | Diagnostic child process for real-process transport tests; never used at runtime | n/a |

Canonical graph goldens belong to the consuming application, not here.

`transactional_snapshot_companion/` records historical protocol-version-3, validation-version-1 snapshot
and options exchanges. `transactional_resources/` carries the exact shared
error schema/fixtures from companion commit `5cab95e`, plus fresh raw executable
recovery exchanges. Artifact hashes and the source/binary identity are recorded
in `docs/evidence/transactional_companion.provenance.json`. Historical captures
are preserved unchanged.

Current Stage 3 evidence uses these directories:

- `scope_aware_snapshot_companion/`: snapshot and options exchanges, source pin,
  binary identity, certification and zero-allocation cleanup.
- `scope_aware_resources/`: unchanged shared resource schema/fixtures and fresh
  native resource exchanges against the validation-version-2 executable.
- `scope_aware_validation/`: exact shared validation schema/fixtures from
  `ba2c3dd`, fresh core and Mathlib exchanges, owner/residue diagnostics and
  pinned Mathlib source verification. `capture.json` preserves the raw harness
  default serialization options. `client_capture.json` enables client-required
  model expressions and is checked by the full response decoder.

`docs/evidence/scope_aware_companion.provenance.json` records the matched pair
and artifact hashes. Prior directories retain their original bytes and identities.
