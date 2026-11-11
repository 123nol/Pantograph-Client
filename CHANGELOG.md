# Changelog

## 0.6.0 (unreleased)

- Add `pantograph_async.evidence`: request events reported to an optional
  observer before each write and after each outcome, and a bounded, immutable
  `FailureSnapshot` for the last failed request (`client.last_failure`, final
  after `aclose()`). An observer failure before the write sends nothing.
- Recognize the REPL's version-1 `pantograph-command-failure` stderr records and
  associate one with the failed request only when it is unambiguous.
- Pin companion `661df4e`: elaboration aborts (`exact`/`refine`/`have` with a
  placeholder Lean cannot synthesize) are ordinary tactic rejections, and
  unexpected failures write the stderr record. Add current
  `failure_diagnostics_*` captures; earlier captures stay historical.
- The stdout contract, contract revision 6 and recovery classes are unchanged.

## 0.5.0 (unreleased)

- Require transition validation version 3 and the exact
  `execution-closure-and-representation-aware-audit` scope. Reject validation
  versions 1 and 2 during startup and response decoding. Overall protocol remains
  version 3. Client contract revision is 6.
- Pin companion `fc740c2`, which reads compiler-stage environment entries by
  their representation. Tactics that compile an on-demand match splitter, such as
  `unfold Nat.pow`, no longer end the session; compiler-only entries are never
  proof dependencies.
- Refresh the reproducible patch and native source/binary identities, and add
  current `compiler_aware_*` captures; all earlier captures stay historical.
- Check compiler-producing transitions, continuation, inspection and kernel
  certification against the native companion, including the pinned Mathlib gate,
  and startup rejection of the validation-version-2 executable.
- Validation integrity failures remain terminal. Application and deployment
  migration remain separate stages.

## 0.4.0 (unreleased)

- Require transition validation version 2 and the exact
  `execution-closure-and-transition-audit` scope. Reject validation version 1
  during startup and response decoding. Overall protocol remains version 3.
- Pin published companion `ba2c3dd`, refresh the reproducible patch and native
  source/binary identities, and preserve all earlier captures as historical.
- Verify owned `tauto` transitions, inspection, alternative and sibling execution,
  root certification, and lexical cleanup against pinned Mathlib.
- Keep dangling execution references terminal, preserve allocation ownership and
  transactional resource recovery, and check the shared validation fixtures.
- Add a separate opt-in Mathlib client gate; core CI has no Mathlib dependency.
  Application and deployment migration remain separate stages.

## 0.3.0 (unreleased)

- Require protocol version 3 with resource-error and command-transaction versions
  1, across startup and all runtime commands. Client contract revision is 4.
- Expose typed recoverable resource, fatal session resource, and remote internal
  errors. Preserve allocations on validated rollback; retire fatal sessions.
- Keep explicit deletion ownership on rollback and retire sessions when lexical
  cleanup fails, preserving the original operation exception.
- Bound exception payloads and include offending stdout, command, session and
  phase in protocol diagnostics.
- Pin the published transactional companion `5cab95e`, reproduce its sources
  with the bundled patch, and record native recovery and snapshot exchanges.
  Remove the obsolete `printJsonPretty` option; revision 3 always uses compact JSON.
- Verify the companion descriptor against the codec before exposing build pins.
  CI builds and runs the Lean tests and raw resource harness before the client gate.
- Use the companion's native reduction fixture for heartbeat recovery and test
  fatal internal shutdown against the real executable.
- Application migration and deployment remain pending.

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
