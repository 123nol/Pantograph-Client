# Wire protocol

The client speaks exactly one contract, revision 6 of the custom REPL
(`src/pantograph_async/resources/contract.json`). The codec in
`pantograph_async.protocol` rejects anything else; there is no fallback schema.

## Session

The REPL is launched as `stdbuf -oL <repl> <imports...>` in `source_root`, with
`LEAN_PATH` from `lake env printenv LEAN_PATH`. It must print `ready.` and then
answer one JSON line per request line `<command> <json>`.

Startup, under one deadline:

1. `protocol.describe` must return exactly this descriptor:

   | Field | Value |
   | --- | --- |
   | `protocol` | `maths-ai-pantograph` |
   | `protocolVersion` | 3 |
   | `resourceErrorVersion` | 2 |
   | `commandTransactionVersion` | 1 |
   | `modelSexpVersion` | 1 |
   | `transitionValidationVersion` | 3 |
   | `transitionProvenanceVersion` | 1 |
   | `inspectionVersion` | 1 |
   | `certificationVersion` | 1 |
   | `messageVersion` | 1 |
   | `goalSelection` | `explicit-focused-v1` |
   | `tacticErrorsFormat` | `string-array-v1` |

   The protocol name keeps its historical application name. Renaming the Python
   package does not change it.
2. `options.set` applies the required options (`printExprPretty`, `printExprAST`, `printExprModelAST`, `automaticMode` true,
   `noRepeat=false`). Conflicting values are rejected before any request.
3. `options.print` must report every requested option as applied.

Revision 3 always emits compact JSON lines. `printJsonPretty` is removed from
both option requests and responses; the client rejects it.

## Commands

| Command | Request | Success |
| --- | --- | --- |
| `goal.start` | `{"expr"}`, optional `{"levels"}` | `{"stateId", "root"}` |
| `goal.tactic` | `{"stateId", "goalId", "tactic"}` | see below |
| `goal.delete` | `{"stateIds"}` (unique) | `{}` |
| `goal.inspect` | `{"stateId", "goals"}` (nonempty, distinct) | `{"obligations"}` |
| `goal.certify` | `{"stateId"}`, optional positive `{"maxHeartbeats"}` | see below |
| `stat` | `{}` | `{"nGoals"}` |

`levels` is the REPL's existing universe-parameter list for `goal.start`: the
server declares each name with `String.toName` before elaborating `expr`. It is
sent only when nonempty, so a goal without named universes keeps the original
request bytes. Each entry must be a unique atomic ASCII identifier
(`[A-Za-z_][A-Za-z0-9_']*`, not `_`, `max` or `imax`); a dotted name would become
a hierarchical name on the server. Invalid lists are rejected before anything is
sent. Exposing this field changes no descriptor version.

`goalId` is always sent explicitly. Omission is not unfocused execution.
Ordinary errors are `{"error", "desc"}` with a per-command category set. `goal.start`
parse/elaboration errors map to `PantographGoalRejected`; an unknown state
or obligation index on `goal.tactic`, `goal.inspect` or `goal.certify` maps to
`PantographStateError`; everything else is a protocol error.

## Tactic responses

Exactly one of three variants, each with `messages`, `hasSorry` and `hasUnsafe`:

- success: `nextStateId`, `goals`, `transition` (below), and `validation` =
  `{"version": 3, "scope": "execution-closure-and-representation-aware-audit", "checked": true}`.
  A logged error message cannot accompany a success.
- `parseError`: a nonempty string.
- `tacticErrors`: a nonempty string array.

Failed variants must carry false flags. A success with `hasSorry` or
`hasUnsafe` is an admission/unsafe rejection: the client deletes the new state
and raises `PantographTacticRejected` with the decoded success as payload.

Goals carry `name`, optional `userName` (case tag), `fragment`
(`tactic`/`conv`/`calc`, consistent with `isConversion`), a target expression,
and `vars`. Locals have unique increasing `contextIndex` values (gaps allowed),
a binder role consistent with `isInstance`/`isLet`, and a `value` exactly when
they are `let`. Every expression has `pp`, `sexp`, `modelSexp` and
`modelSexpVersion`, plus optional `dependentMVars`.

Messages have `kind`, `severity` (`information`/`warning`/`error`), `data`,
`pos` and optional `endPos`. Position `(0, 0)` means unavailable.

## Transition provenance

`transition` is `{version: 1, selected, direct, introduced, siblings, changed,
closed, dormant, extra}`. `direct` lists the goals the tactic produced for
`selected`, in tactic order and before automatic sibling resumption;
`introduced[i]` lists the locals `direct[i]` has that `selected` lacks.
`siblings` are input goals still listed, `changed` the siblings whose
instantiated target or locals changed, `closed` the input goals the transition
assigned, `dormant` those unassigned but no longer listed, and `extra` any other
listed obligation. A tactic that leaves `selected` open, such as `skip`, lists
it as its own direct goal. The codec requires `direct`, `siblings` and `extra`
to partition `goals`, `selected`, `closed` and `dormant` to be distinct,
`closed` and `dormant` to be unlisted, a listed `selected` to be direct,
`changed` to be siblings and every introduced local to be in its
goal's context. The scope also requires `selected` to name the goal it asked
for. A violation retires the session.

Names are Lean metavariable and local IDs. They are valid only inside one
session's state lineage and change when the same tactics are replayed.

## Inspection

Each obligation is `{name, status, holes, universeHoles}` plus `goal` for the
`active` and `pending` statuses. `complete` has no holes; `assigned` and
`delayed` report at least one. Obligations come back in request order, which
the scope checks. Inspection allocates nothing.

## Certification

`{version: 1, status, reason?, receipt?}` with status `certified`, `incomplete`,
`rejected` or `inconclusive` (a kernel resource limit). Exactly `certified`
carries a receipt and no reason: `{version, identity: "lean-expr-digest-v1",
root, levels, rootType, proof, environment, lean, axioms, auxiliary}`, where the
three digests are 16 lowercase hex digits. The scope requires the receipt's
root to be the root the state descends from. The check is the server's kernel
check of the started statement, not an interpretation of `goals == []`. A
request timeout retires the session like any other.

## Execution types

Decoded values are frozen dataclasses (`ExecutionGoal`, `ExecutionLocal`,
`WireExpression`, `TacticState`, `TransitionProvenance`,
`ObligationInspection`, `CertificationResult`, ...). They expose wire fields only. Converting
them into an application model is the consumer's job, in its own adapter.

## Transactional resource failures

Every command, including startup probes and deletion, can return:

```json
{"error":"resource","desc":"Lean command heartbeat budget exhausted","resource":{"version":2,"kind":"heartbeats","phase":"execute","limit":200000},"recovery":"command-rolled-back"}
{"error":"resource","desc":"Lean maximum recursion depth reached","resource":{"version":2,"kind":"recursion-depth","phase":"execute","limit":512},"recovery":"command-rolled-back"}
```

`version` is 2. `kind` is `heartbeats` or `recursion-depth`; any other kind or
version is a protocol error. `phase` is `execute`, `validate`, `observe`, or
`serialize`. `limit` is a positive integer in the kind's units: Lean's
`maxHeartbeats` option units for `heartbeats`, and the command's configured
`maxRecDepth` (nesting levels) for `recursion-depth`; booleans are invalid. No extra fields are accepted.
The pending request supplies the command identity.

`command-rolled-back` raises `PantographResourceError`, directly in the
`PantographError` family. Prior state objects remain usable. No allocation is
registered or consumed, and deletion rollback retains ownership. The client
never retries automatically. Rollback does not reverse arbitrary external IO.

`session-unusable` raises `PantographSessionResourceError`, in the
`PantographTransportError` family. Unexpected remote failures return
`{"error":"internal","desc":"Unexpected REPL command failure","recovery":"session-unusable"}`
and raise `PantographRemoteInternalError` in the same transport family.
Both fatal outcomes invalidate all handles, reap the process, and wake queued
requests with the retained cause before they can write.

Resource exceptions expose read-only `kind`, `phase`, `limit`, `recovery`, and
frozen `resource` metadata, plus independently copied `payload` context.
A startup resource error closes the process and surfaces its typed error with
command and resource phase. It never publishes a READY client.

Explicit release can be attempted again after validated deletion rollback.
Lexical cleanup failure closes the session to reclaim all allocations. An
operation error already propagating remains the primary exception, with the
cleanup error recorded in its notes. Cleanup failure without a prior error
raises the deletion error. Subsequent client requests raise a transport failure
with the deletion rollback as its cause because the owner retired the session.

Unknown stdout, duplicate responses, invalid JSON/schema, and interruptions
after a possible write remain terminal. Protocol diagnostics include a bounded
stdout prefix, pending command, session identity, session phase, and stderr tail.
Exception messages and wire payload context are bounded to 4096 characters;
resource descriptions are bounded to 2048 characters.

## Representation-aware transition checking

`TRANSITION_VALIDATION_VERSION` is 3 and `TRANSITION_VALIDATION_SCOPE` is
`execution-closure-and-representation-aware-audit`. The decoder requires both values and
`checked: true`. Validation versions 1 and 2, the older scopes, missing fields,
booleans in integer fields, and unknown metadata fields are rejected. Protocol version 3
and the resource, transaction, model, provenance, inspection and certification
versions are unchanged.

The REPL strictly checks the executable dependency closure under each expression's
owner and audits auxiliary retained syntax for hazards. An inert elaboration
record can contain an unresolved local outside that closure without invalidating
a valid tactic. This does not exempt future executable uses of that record.

Version 3 also reads compiler-stage environment entries by their representation.
Tactics that generate equations or match splitters (`unfold Nat.pow`,
`simp only [Nat.pow]`, `rw [Nat.pow]`) compile them, and the code generator stores
`_cstage1`/`_cstage2` entries in the retained environment. The REPL accepts such
an entry only when the compiler registered IR for its owner, audits it as runtime
data, and never lets a proof depend on it. Compiler-only entries are not proof
constants and never appear in a certificate's auxiliary declarations; kernel
certification of the original root remains authoritative. The client does not
classify compiler data itself. A version-2 executable ended the session on those
tactics, and its validation error remains a terminal `PantographProtocolError`.
The client accepts the checked response through its existing allocation owner.

A genuine `error: validation` remains `PantographProtocolError`. Snapshot
validation can fail on start, tactic, inspection or certification. The session
is retired and all handles are invalidated; no candidate-rejection or resource
exception is substituted. Kernel certification of the original root remains the
proof-success boundary.

## Request evidence and failure snapshots

`pantograph_async.evidence` holds plain, immutable records; none of them keeps a
state, handle, process or future.

- `PantographClient.create(env, observer=...)` takes an optional callable that
  receives a `RequestEvent` for every serialized request: `prepared` before the
  write, then `completed` or `failed`. Each event has the session and process,
  the client's own `sequence`, the operation, the bounded request line, the
  selected `state_id`/`goal_index`, and on `completed` the `allocated_state_id`
  of a new state, so a replay can map recorded states to fresh ones. If the observer raises on `prepared`, the
  command is not written and `PantographCaptureError` is raised; the session and
  its states are unaffected. If it raises later, the request's result stands and
  the error is kept in `client.capture_errors`.
- `client.last_failure` is a `FailureSnapshot` for the most recent failed
  request: the bounded request (16 KiB), how far the exchange got (`waiting`,
  `prepared`, `written`, `decoded`), the exception type, message, notes and
  structured payload (bounded), the timeout source, the stderr tail, and the
  REPL's failure records. Read it after `aclose()` for the final version.
- The REPL writes one stderr line for an unexpected fatal failure: kind
  `pantograph-command-failure`, version 1, with its own `repl_command_sequence`,
  the operation, state, goal, phase, exception category and identifier, and a
  bounded message. `parse_repl_failures` recognizes only that record. A snapshot
  is `matched` to a record only if the record names the same operation, state
  and goal and is the only one; otherwise it is `ambiguous` or `absent`, and
  `repl_failure` stays empty. The two sequence numbers are never assumed equal.

Stdout decoding, recovery classes and session retirement are unchanged.
`PantographRemoteInternalError` still ends the session.

Companion `661df4e` also stops treating Lean's elaboration aborts as unexpected
failures. `exact`, `refine` and `have` with a placeholder Lean cannot
synthesize now give an ordinary `PantographTacticRejected` with Lean's message
instead of ending the session.

Companion `46a33e1` reports Lean's maximum recursion depth as a resource error
with `kind: "recursion-depth"` instead of an unexpected internal failure. A
tactic that exceeds it is rolled back: `PantographResourceError`, the input
state stays usable, and another tactic can be applied to it in the same session.
`frontend.process` keeps `session-unusable` for resource failures; inside a
processed file, Lean's command elaborator reports recursion exhaustion as that
command's error message. Certification that exhausts either limit is
`inconclusive`.
