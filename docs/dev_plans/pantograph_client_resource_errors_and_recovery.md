# Standalone Pantograph client resource errors and recovery

Status: standalone client implementation completed in the working tree on
2026-11-04. The subsequent
[companion live-gate repair](revision3_companion_live_gate.md) completes matched
native validation; application/release delivery gates remain pending.
The implementation notes below record the original standalone handoff before
that follow-up.

Implementation notes:

- The starting checkout was already current at `955a4921b4cacaa49f4b3087f3982d7ca3629566`.
  No main integration was needed. Existing untracked plan material was preserved.
  Implementation branch: `feat/resource-errors-and-recovery`.
- Stages 1–2 and the offline portion of Stage 3 are implemented across the shared
  codec, transaction engine, ownership scopes, exports, fixtures and documentation.
  Package version is `0.3.0` (unreleased), client contract revision 4, wire protocol
  version 3. Contract revision and wire protocol version are distinct counters.
- Authored resource fixtures are in `tests/fixtures/resource_errors.json`.
  No revision-3 native captures are available. The local companion checkout
  `/tmp/pr72-repl` is `9ecaaea242f427e534aff29314513c358b4d21ad`, implementing
  protocol version 2. Historical source/binary identities and captures remain
  unchanged; the manifest explicitly records their historical descriptor.
- Validation on Python 3.13: all 157 new recovery tests pass. Final source
  codec/recovery checks: 459 passed. Final installed-wheel distribution/recovery
  checks, plus the failed broad-run case rerun: 168 passed, 1 opt-in skip.
  An earlier broad source run passed 637 tests; the final broad source run had
  636 passes and one intermittent startup-deadline failure. The final broad
  installed run had 638 passes, 12 skips and one startup-deadline failure; that
  case passed individually. Other attempts hit different existing startup or
  shutdown deadlines. Deadline assertions were not relaxed.
  Two existing cross-event-loop tests were deselected because they stall in this
  sandbox, as does a standalone `asyncio.to_thread` shutdown check. Full clean
  CI execution is still required. Source and wheel archives build, archive-content
  checks pass, and the installed suite uses the unpacked sdist's own support files.
- The native heartbeat rollback/certification gate is added to
  `tests/test_client_live.py` but is unrun without a revision-3 companion.
- Stage 0 native contract agreement/capture, native Stage 3 evidence, Stage 4
  application migration, and Stage 5 release/deployment are not complete. The
  standalone package changes no application dependency or deployment environment.

The architecture and external completion criteria below remain the coordinated
implementation contract.

Companion: [Transactional resource errors in the REPL](pantograph_repl_transactional_resource_errors.md).
Both plans define the same revision-3 wire contract. Application migration is
required before describing this work as a complete RL recovery fix.

## Objective and source basis

The JupyterHub REPL printed `Uncaught IO exception` followed by a deterministic
heartbeat timeout at `whnf`. The client correctly rejected the unexpected stdout,
but the resulting protocol exception concealed the useful resource category and
terminated the training run.

The scope change is to distinguish a valid, rolled-back command resource failure
from a broken session. The shared codec, transaction engine, ownership scopes,
all exposed command methods, and application callers must support that
distinction together. Do not add a special case only in MCTS tactic execution.

The inspected implementation is `123nol/Pantograph-Client` at the application's
pinned commit `955a4921b4cacaa49f4b3087f3982d7ca3629566`, available for inspection
under `/tmp/pr72-deps/pantograph_async`. It implements protocol revision 2 and
retained snapshot inspection/certification. The separate local checkout at
`/home/nolawi/Pantograph-Client` is the older
`d1dac7e8a8ea296192e7a5b2616114b73e0812b7`, which implements revision 1. Do not
base this repair on that checkout without integrating current main first.

Implement in a branch/worktree of the standalone repository. The application's
`experiments/custom-client` is historical extraction material, not the package
to patch. Recheck current revisions before starting and preserve unrelated work.

Inspected problem locations:

- `src/pantograph_async/protocol.py`: strict descriptor, command error categories,
  `CommandError.as_exception`, and response decoding.
- `src/pantograph_async/client.py`: `_read_stdout`, `_exchange`, startup handshake,
  and `PantographStateScope` allocation ownership.
- `src/pantograph_async/__init__.py`: public exports.
- `tests/test_protocol.py`, `test_transport.py`, `test_state_scopes.py`,
  `test_client_live.py`, and installed-distribution tests.

`_exchange` currently preserves ordinary goal rejections but treats unfamiliar
exceptions after a write as protocol/bookkeeping failures. Adding a resource
exception class without migrating that control flow would still close the
session or wrap the exception incorrectly.

## Alternatives considered

| Approach | Benefits | Limitations | Decision |
| --- | --- | --- | --- |
| Ignore non-JSON stdout | Appears to tolerate the observed text | Can associate a later response with the wrong request; server may already be exiting | Reject |
| Parse English timeout messages | No coordinated schema work | Brittle and cannot prove snapshot preservation | Reject |
| Replace the worker after every resource error | Simple ownership boundary | Discards safe retained snapshots and prevents candidate-level recovery | Use only for unusable sessions |
| New typed outcomes over transactional REPL errors | Preserves safe sessions and exposes failure meaning | Requires coordinated server and caller migration | Chosen |
| Retry every failed command automatically | May hide transient failure | Repeats deterministic expensive work and can duplicate uncertain mutations | Reject |

## Shared wire contract

Require protocol revision `3`, `resourceErrorVersion: 1`, and
`commandTransactionVersion: 1`. Preserve other model, transition, inspection,
and certification versions. Missing/mismatched descriptors fail startup before
accepting application work. Do not silently support an older error contract.

Recoverable resource envelope:

```json
{
  "error": "resource",
  "desc": "Lean command heartbeat budget exhausted",
  "resource": {
    "version": 1,
    "kind": "heartbeats",
    "phase": "execute",
    "limit": 200000
  },
  "recovery": "command-rolled-back"
}
```

`resource.kind` initially accepts only `heartbeats`. `phase` is `execute`,
`validate`, `observe`, or `serialize`. `limit` is a positive integer in Lean's
`maxHeartbeats` option units, not seconds. Reject booleans as integer values.
`recovery` is either `command-rolled-back` or `session-unusable`.

`command-rolled-back` means no new state was published and all prior session
allocations remain valid. It does not promise reversal of arbitrary external IO.

Unexpected server failures use a separate envelope:

```json
{
  "error": "internal",
  "desc": "Unexpected REPL command failure",
  "recovery": "session-unusable"
}
```

Resource envelopes may also specify `session-unusable`. Internal errors must
never claim recoverable rollback. Reject mixed success/error fields, unknown
fields, unknown kinds/versions, missing metadata, and invalid recovery values.
Existing ordinary command errors retain their previous validated structures.
Use pending-request context as the authoritative command identity.

## Stage 0 — Coordinate fixtures and compatibility

1. Agree the exact descriptor and error fixtures with the REPL implementer.
   Store valid rollback/fatal cases and malformed cases as test data.
2. Record the rebuilt companion source and executable identities. Inspect native
   captured exchanges rather than relying only on a Python fake server.
3. Inventory every command and caller: starts, tactics, inspection, certification,
   deletion, stats, options, startup probes, live application adapters, admission,
   replay, collection, API recovery, CLI diagnostics, examples, and tests.
4. Describe this as a coordinated protocol revision. The new server/client pair
   must be deployed together. External compatibility is a release consideration,
   not permission to add an unreviewed fallback parser.

Exit gate: identical contract definitions and an explicit deployment order.

## Stage 1 — Typed codec and public exceptions

1. Add strict decoded resource/internal error records and include them in the
   public response union. Validate every field before constructing an exception.
2. Add `PantographResourceError`, deriving directly from `PantographError`, for
   `command-rolled-back` resource errors. Expose immutable typed kind, phase,
   limit, and recovery information plus independently copied wire context.
   Do not inherit from `PantographTacticRejected` or `PantographGoalRejected`;
   resource failures can arise on any command and are not proof/input defects.
3. Add `PantographSessionResourceError` for resource errors with unusable
   sessions and `PantographRemoteInternalError` for unexpected fatal errors.
   Derive both from the existing transport/session-failure family so existing
   worker retirement can recognize unusable sessions, retaining their distinct
   concrete types and diagnostic metadata.
4. Migrate command error decoding without relaxing existing schemas. All exposed
   commands may return these envelopes, including cleanup and startup commands.
5. Update descriptor decoding/constants, exports, type annotations, fixtures,
   compatibility documentation, and examples together.

Exit gate: codec tests verify all valid/invalid cases, exception inheritance,
immutable metadata, and unchanged ordinary tactic-error behavior.

## Stage 2 — Transaction and ownership handling

1. In `_exchange`, distinguish decoded recoverable resource exceptions from
   parser failures and transaction bookkeeping errors. Propagate them unchanged
   before the generic exception wrapper. Retain normal lock/future cleanup.
2. Keep a session READY only after a fully validated rolled-back response. Do
   not register or adopt an allocation, create a scope record, mark an input
   consumed, or invoke success bookkeeping on that response.
3. For unusable-session envelopes, mark the session failed, close/reap the owned
   process, invalidate all handles, wake pending operations with the retained
   typed cause, and reject later requests. Do not reuse an uncertain process.
4. Preserve the existing uncertain-write rule: cancellation, IO failure, malformed
   JSON, unexpected stdout, and request timeout after a write close the session.
   A nearby resource response must not convert such an interruption into safe
   recovery.
5. Cover `goal.start`, `goal.tactic`, `goal.inspect`, `goal.certify`, `goal.delete`,
   options and stats uniformly. Existing input state objects stay valid after a
   recoverable error, but never after fatal retirement.
6. Deletion rollback leaves the corresponding allocations registered. Explicit
   release surfaces the error without pretending the state was deleted. If
   lexical scope cleanup cannot delete owned states, close the whole session;
   do not leave leaked Lean allocations behind a successfully closed scope.
   Preserve the original operation error while recording cleanup failure.
7. A resource failure during startup must not produce a READY client. Close and
   surface startup failure with its typed cause and phase. No automatic retries.

Exit gate: a failed tactic followed by a successful tactic on the same input
works without allocation growth; failed cleanup either completes legitimately
or reaps the entire unusable session.

## Stage 3 — Bounded diagnostics and tests

1. Improve failure context to include command name, session/phase, bounded
   offending stdout representation, and existing bounded stderr tail. Never
   retain unlimited response payloads or serialize every model expression into
   an exception. Preserve enough original error context to distinguish a native
   exception from malformed framing without the temporary monkeypatch launcher.
2. Extend the current fake-REPL fixture with recoverable resource errors for each
   command, fatal resource/internal errors, fragmented delivery, cancellation
   races, duplicate/plain-text responses, and failed deletion.
3. Test two queued requests: the first returns rolled-back resource exhaustion,
   the second succeeds with the correct response. A fatal first response must
   prevent the second from writing into the failed session.
4. Assert exact registration, weak-reference reclamation, live-ID tracking,
   cancellation cleanup, and stale/cross-session handle rejection.
5. Run native tests against the revision-3 companion: a real heartbeat failure,
   continued use of the original state, successful simple certification, and
   final zero allocations/process cleanup. Include cumulative-request coverage
   from the REPL plan.
6. Run the full existing suite, build wheel and sdist, and execute packaged tests
   using the unpacked sdist's own support files. Confirm application/Lean helper
   dependencies have not entered the standalone client package.

Exit gate: fake transport and native evidence both demonstrate safe recovery;
all fatal cases remain terminal and no plain-text output is silently skipped.

## Stage 4 — Required application migration

This stage is a consumer integration dependency, not code to place in the
standalone package. Without it, a typed recoverable error can still escape the
reasoner and terminate training. Implement all current callers together in the
application branch and port the common changes to the other supported branches.

Inspect at least:

- `maths_ai/hybrid_reasoner/retained_executor.py` and `execution_registry.py`.
- Replay/certification coordinators and both PUCT and best-first expansion.
- `maths_ai/gnn_inference/atp_lean_gnn/seed_admission.py`,
  `rl_live_collection.py`, `live_runtime.py`, evaluation/driver code and metrics.
- `maths_ai/api/runtime_backend.py`, supervisor/result handling, diagnostics,
  native tests, and any other direct client callers found by symbol search.

Consumer semantics:

1. A rolled-back tactic resource failure closes its in-flight result reservation
   without adoption, preserves the source lease, and consumes that candidate's
   attempt budget. Search may try other proposals under the theorem deadline.
   Do not retry the identical expensive action indefinitely.
2. Resource failure is a distinct operational outcome/counter. Do not feed it
   into the ordinary mathematically rejected-action actor examples or report a
   valid transition, successful replay, or certificate. Document RL accounting
   and retain critic/search records only when their existing semantics apply.
3. A replay/inspection/certification resource failure leaves proof completion
   unestablished. Handle it at the operation that owns the replay attempt and
   enforce existing combination/step/time budgets before trying alternatives.
   No uncertified graph recipe becomes theorem success.
4. Admission resource failure is not malformed theorem input. Report it
   separately; do not persistently quarantine the seed as a reconstruction
   defect or cache it as validated. If there are no usable admitted seeds, end
   with an explicit operational admission outcome instead of fabricating data.
5. Fatal session errors use the existing retire-and-replace path with bounded
   replacement attempts. Destroy all theorem-local references to the old session.
   Recovery cannot transfer retained handles to the replacement client.
6. Migrate metrics and API result records to retain resource kind/phase and fatal
   versus recoverable classification. Do not claim that remote computation
   exhaustion proves the goal unsatisfiable or the supplied statement invalid.

Validate a resource failure followed by another viable tactic, replay resource
failure, fatal worker replacement, admission accounting, and final kernel
certification. Exercise both search modes, RL collection, CLI evaluation, and
the API. Bound every path using the existing shared registry/resource owners.

Exit gate: the application continues when safe, stops/replaces when necessary,
and does not corrupt snapshots, rewards, or proof-success accounting.

## Stage 5 — Release and deployment

1. Merge and build the REPL companion first, then validate and release the client
   against its exact source/binary identity.
2. Pin the reviewed client commit in application dependencies, regenerate
   `uv.lock` and exported requirements, and land all caller changes together.
   Update Docker REPL pins/provenance and native compatibility documentation.
3. Deploy the client and executable as a matched pair during a controlled restart.
   Do not replace a running session's executable or patch installed package files.
4. Update JupyterHub with the pinned package and newly built executable. Run a
   deterministic native recovery smoke before the source-aware MCTS RL trial.
5. Run a real Docker build/container smoke, then a GPU/trained-checkpoint trial
   where available. Keep those results separate from fake/native unit tests.
6. Verify environment/deployment manifests and exact-resume identities. A changed
   binding may require legitimate regeneration or a fresh run; do not edit hashes
   or add a compatibility bypass.

## Completion criteria

- Structured recoverable resource errors leave a usable client and valid inputs.
- Unusable sessions are reaped and old handles cannot execute again.
- Scope cleanup and registry reservations remain bounded through every error path.
- No unknown stdout or malformed response is silently accepted.
- All application callers understand the new outcomes and enforce existing limits.
- The original timeout can be diagnosed by command/phase, and deterministic
  resource tests no longer terminate the entire RL run when rollback is safe.
