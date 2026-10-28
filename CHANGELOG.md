# Changelog

## 0.2.0 (unreleased)

Contract revision 3 for protocol version 2 of the companion REPL. Servers that
report protocol version 1 are rejected at startup.

- Every `TacticState` carries `transition`, a `TransitionProvenance` saying which
  goals the tactic produced for the selected goal (with the locals each
  introduced), which are surviving siblings and which of those changed, and
  which siblings were closed or left dormant. The codec checks that it
  partitions the returned goals, and the scope checks that it names the
  requested goal.
- `PantographStateScope.inspect(state, names)` reads named obligations of a live
  state, including ones it no longer lists: `active`, `pending`, `assigned`,
  `delayed` or `complete`, with their remaining holes.
- `PantographStateScope.certify(state, max_heartbeats=None)` asks the REPL's
  kernel to check the complete root proof against the started statement. Only
  `certified` results carry a `CertificateReceipt`, whose root must be the
  state's own root.
- Released states no longer stay referenced until scope exit. Each live
  allocation keeps one weak reference to its issued object, keyed by a new
  `StateHandle.allocation` number, so released and dropped states can be
  collected while copies and foreign states are still rejected.
- The companion is now `123nol/Pantograph` `client_centric_repo` at `9ecaaea`
  (the merge of 123nol/Pantograph#1), recorded as `source_commit`; the patch,
  source digests and reference binary hash are updated, and a live capture of
  the new operations is in `tests/fixtures/snapshot_companion`.

## 0.1.1 (unreleased)

- `PantographStateScope.start_goal(expression, *, levels=())` sends the REPL's
  existing `goal.start` `levels` field, so goals over named universe parameters
  such as `Type u_1` elaborate. The client only transports and validates the
  names (unique atomic ASCII identifiers, checked before sending); working out
  which levels an expression needs is the caller's job. The request is unchanged
  when no levels are given, and no descriptor version changes.

## 0.1.0 (unreleased)

First standalone release, extracted from Mathematics-ai-atp `AC-branch` at
`e8e4b18e081d6dd84491433b00e8cfa596cdfbee`.

- Async transport, launch validation, state scopes and the strict codec for
  contract revision 2, unchanged apart from module paths.
- `MODEL_SEXP_VERSION` is owned by the client; execution types no longer
  convert into application models.
- Wire probes (`pantograph_async.probes`) and a live gate that reports which
  checks ran and fails when required checks cannot run.
- `pantograph-client smoke` CLI that needs no checkout or Git metadata.
- Contract, compatibility manifest and companion patch shipped as package data,
  with digest, codec and patched-source checks.
- The spawn-cancellation test gets its own startup budget, fixing a race with
  the helper processes.
- The sdist carries the complete offline suite, fixtures, documentation,
  evidence and example, checked by `scripts/check_sdist.py` in CI; the wheel
  stays runtime-only.
